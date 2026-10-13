#!/usr/bin/env python3
"""Team Tracker Lite - ONE sensor, any team, picked from a web menu.

Pulls game data from ESPN's public API for the single team you mark as
"tracking" and publishes it to Home Assistant over MQTT as one sensor with
the same state values (PRE / IN / POST / NOT_FOUND) and attribute names the
Team Tracker integration uses, so existing cards keep working.
"""
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import paho.mqtt.client as mqtt

VERSION = "0.2.0"
# Settings live in the add-on's config folder (/addon_configs/<id>_team_tracker_lite/data on the host).
DATA = os.environ.get("TTL_DATA", "/config/data")
SETTINGS_FILE = os.path.join(DATA, "settings.json")
OPTIONS_FILE = os.environ.get("TTL_OPTIONS", "/data/options.json")  # written by Supervisor
HERE = os.path.dirname(os.path.abspath(__file__))
ALLOW_ANY = os.environ.get("TTL_ALLOW_ANY") == "1"  # local testing only

ESPN = "https://site.api.espn.com/apis/site/v2/sports"
UA = {"User-Agent": "TeamTrackerLite/0.1 (home-assistant add-on)"}
POST_HOLD_HOURS = 18  # keep showing the final score this long after a game

# id: (menu label, sport path, league path, ESPN "groups" filter for college)
LEAGUES = {
    "NFL": ("NFL", "football", "nfl", None),
    "NBA": ("NBA", "basketball", "nba", None),
    "MLB": ("MLB", "baseball", "mlb", None),
    "NHL": ("NHL", "hockey", "nhl", None),
    "WNBA": ("WNBA", "basketball", "wnba", None),
    "NCAAF": ("College Football (FBS)", "football", "college-football", "80"),
    "NCAAM": ("College Basketball (Men)", "basketball", "mens-college-basketball", "50"),
    "NCAAW": ("College Basketball (Women)", "basketball", "womens-college-basketball", "50"),
    "MLS": ("MLS", "soccer", "usa.1", None),
    "NWSL": ("NWSL", "soccer", "usa.nwsl", None),
    "EPL": ("English Premier League", "soccer", "eng.1", None),
    "LIGA": ("Spanish LaLiga", "soccer", "esp.1", None),
    "BUND": ("German Bundesliga", "soccer", "ger.1", None),
    "SERA": ("Italian Serie A", "soccer", "ita.1", None),
    "LIG1": ("French Ligue 1", "soccer", "fra.1", None),
    "CL": ("Champions League", "soccer", "uefa.champions", None),
}

# MQTT topics
T_AVAIL = "team_tracker_lite/status"
T_STATE = "team_tracker_lite/state"
T_ATTR = "team_tracker_lite/attributes"
T_SEL_SET = "team_tracker_lite/select/set"
T_SEL_STATE = "team_tracker_lite/select/state"
D_SENSOR = "homeassistant/sensor/team_tracker_lite/config"
D_SELECT = "homeassistant/select/team_tracker_lite/config"

LOCK = threading.RLock()
WAKE = threading.Event()
OPTS = {}
S = {}
LAST = {"state": "NOT_FOUND", "attributes": {"api_message": "Starting up"}, "at": None}
TEAM_CACHE = {}
CLIENT = None
MQTT_OK = False
PREV = None  # (active team key, state) - used to log only real state changes
LEVELS = {"debug": 10, "info": 20, "warning": 30, "error": 40}
LOG_LEVEL = LEVELS["info"]


def log(level, *a):
    if LEVELS.get(level, 20) >= LOG_LEVEL:
        print(time.strftime("%H:%M:%S"), f"[{level.upper()}]", *a, flush=True)


# ---------------------------------------------------------------- settings
def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def load_settings():
    s = load_json(SETTINGS_FILE, {})
    s.setdefault("sensor_name", "Team Tracker")
    s.setdefault("favorites", [])
    s.setdefault("active", None)
    s["idle_minutes"] = clamp(s.get("idle_minutes"), 1, 60, 10)
    s["live_seconds"] = clamp(s.get("live_seconds"), 5, 120, 15)
    return s


def clamp(v, lo, hi, default):
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def init_storage():
    """Make sure the settings folder exists and is writable; fall back to /data if not."""
    global DATA, SETTINGS_FILE
    try:
        os.makedirs(DATA, exist_ok=True)
        probe = os.path.join(DATA, ".write_test")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as e:
        log("warning", f"Cannot write to {DATA} ({e}); falling back to /data. "
                       "Settings will not appear in addon_configs.")
        DATA = "/data"
        SETTINGS_FILE = os.path.join(DATA, "settings.json")
        os.makedirs(DATA, exist_ok=True)


def save_settings():
    os.makedirs(DATA, exist_ok=True)
    tmp = SETTINGS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(S, f, indent=2)
    os.replace(tmp, SETTINGS_FILE)
    log("debug", "Settings saved to", SETTINGS_FILE)


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "team_tracker"


def active_fav():
    with LOCK:
        for f in S["favorites"]:
            if f["key"] == S["active"]:
                return dict(f)
    return None


# -------------------------------------------------------------------- ESPN
def http_json(url, timeout=15):
    log("debug", "GET", url)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def get_teams(lid):
    cached = TEAM_CACHE.get(lid)
    if cached and time.time() - cached[0] < 6 * 3600:
        return cached[1]
    _, sport, lg, groups = LEAGUES[lid]
    q = {"limit": "1000"}
    if groups:
        q["groups"] = groups
    d = http_json(f"{ESPN}/{sport}/{lg}/teams?{urllib.parse.urlencode(q)}")
    out = []
    for item in d["sports"][0]["leagues"][0]["teams"]:
        t = item["team"]
        out.append({
            "id": str(t["id"]),
            "abbr": t.get("abbreviation", ""),
            "name": t.get("displayName") or t.get("name", ""),
            "logo": ((t.get("logos") or [{}])[0]).get("href", ""),
        })
    out.sort(key=lambda x: x["name"])
    TEAM_CACHE.clear()  # only ever hold one league in RAM
    TEAM_CACHE[lid] = (time.time(), out)
    return out


def fetch_schedule(lid, tid):
    _, sport, lg, _g = LEAGUES[lid]
    base = f"{ESPN}/{sport}/{lg}/teams/{tid}/schedule"
    events = {}
    for suffix in ("", "?seasontype=3"):  # regular/current + postseason
        try:
            d = http_json(base + suffix)
        except Exception:
            if suffix == "":
                raise
            continue
        for e in d.get("events") or []:
            events[str(e.get("id"))] = e
    return list(events.values())


def fetch_scoreboard_event(lid, eid):
    _, sport, lg, groups = LEAGUES[lid]
    q = {"limit": "400"}
    if groups:
        q["groups"] = groups
    d = http_json(f"{ESPN}/{sport}/{lg}/scoreboard?{urllib.parse.urlencode(q)}")
    for e in d.get("events") or []:
        if str(e.get("id")) == str(eid):
            return e
    return None


# ----------------------------------------------------------- data shaping
def parse_dt(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def comp_of(e):
    return (e.get("competitions") or [{}])[0]


def status_of(e):
    return comp_of(e).get("status") or e.get("status") or {}


def state_of(e):
    return (status_of(e).get("type") or {}).get("state")


def num(v):
    if isinstance(v, dict):
        v = v.get("displayValue", v.get("value"))
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def cid(c):
    return str(c.get("id") or (c.get("team") or {}).get("id"))


def record_of(c):
    for key in ("records", "record"):
        lst = c.get(key) or []
        for r in lst:
            if r.get("type") == "total":
                return r.get("summary") or r.get("displayValue")
        if lst:
            return lst[0].get("summary") or lst[0].get("displayValue")
    return None


def tv_of(comp):
    names = []
    for b in comp.get("broadcasts") or []:
        if isinstance(b.get("names"), list):
            names += b["names"]
        elif isinstance(b.get("media"), dict):
            names.append(b["media"].get("shortName") or "")
    names = [n for n in names if n]
    return ", ".join(names) or None


def humanize(delta):
    secs = int(delta.total_seconds())
    if secs < 0:
        return None
    if secs < 3600:
        return f"in {max(1, secs // 60)} minutes"
    if secs < 86400:
        h = secs // 3600
        return f"in {h} hour{'s' if h != 1 else ''}"
    d = round(secs / 86400)
    return "tomorrow" if d <= 1 else f"in {d} days"


def side(p, c, a):
    c = c or {}
    t = c.get("team") or {}
    rk = (c.get("curatedRank") or {}).get("current")
    a[p + "_abbr"] = t.get("abbreviation")
    a[p + "_id"] = cid(c) if c else None
    a[p + "_name"] = t.get("name") or t.get("nickname") or t.get("shortDisplayName")
    a[p + "_long_name"] = t.get("displayName")
    a[p + "_record"] = record_of(c)
    a[p + "_rank"] = rk if isinstance(rk, int) and 0 < rk <= 25 else None
    a[p + "_homeaway"] = c.get("homeAway")
    a[p + "_logo"] = t.get("logo") or ((t.get("logos") or [{}])[0]).get("href")
    a[p + "_colors"] = ["#" + x for x in (t.get("color"), t.get("alternateColor")) if x]
    a[p + "_score"] = num(c.get("score"))
    a[p + "_winner"] = c.get("winner")


def build(event, tid, lid):
    comp = comp_of(event)
    cs = comp.get("competitors") or []
    me = next((c for c in cs if cid(c) == str(tid)), None)
    if not me:
        return None
    op = next((c for c in cs if c is not me), None)
    st = status_of(event)
    stype = st.get("type") or {}
    state = {"pre": "PRE", "in": "IN", "post": "POST"}.get(stype.get("state"), "NOT_FOUND")
    label, sport, lg, _g = LEAGUES[lid]
    now = datetime.now(timezone.utc)
    when = parse_dt(event.get("date") or comp.get("date"))
    venue = comp.get("venue") or {}
    addr = venue.get("address") or {}
    sit = comp.get("situation") or {}
    odds = (comp.get("odds") or [{}])[0]

    a = {
        "sport": sport,
        "sport_path": sport,
        "league": label,
        "league_id": lid,
        "league_path": lg,
        "event_name": event.get("name"),
        "date": when.isoformat() if when else None,
        "kickoff_in": humanize(when - now) if when and state == "PRE" else None,
        "venue": venue.get("fullName"),
        "location": ", ".join(x for x in (addr.get("city"), addr.get("state")) if x) or None,
        "tv_network": tv_of(comp),
        "odds": odds.get("details") if state == "PRE" else None,
        "overunder": odds.get("overUnder") if state == "PRE" else None,
        "quarter": st.get("period") if state == "IN" else None,
        "clock": st.get("displayClock") if state == "IN" else None,
        "status_detail": stype.get("shortDetail") or stype.get("detail"),
        "last_play": (sit.get("lastPlay") or {}).get("text") if state == "IN" else None,
        "down_distance_text": sit.get("downDistanceText") if state == "IN" else None,
        "possession": sit.get("possession") if state == "IN" else None,
        "outs": sit.get("outs") if state == "IN" else None,
        "balls": sit.get("balls") if state == "IN" else None,
        "strikes": sit.get("strikes") if state == "IN" else None,
        "on_first": bool(sit.get("onFirst")) if state == "IN" and "onFirst" in sit else None,
        "on_second": bool(sit.get("onSecond")) if state == "IN" and "onSecond" in sit else None,
        "on_third": bool(sit.get("onThird")) if state == "IN" and "onThird" in sit else None,
        "event_url": next((l.get("href") for l in event.get("links") or []
                           if "summary" in (l.get("rel") or [])), None),
        "last_update": now.isoformat(),
        "api_message": "ok",
    }
    side("team", me, a)
    side("opponent", op, a)
    return state, a


def pick_event(events, now):
    good = []
    for e in events:
        stp = status_of(e).get("type") or {}
        if stp.get("name") in ("STATUS_POSTPONED", "STATUS_CANCELED"):
            continue
        d = parse_dt(e.get("date") or comp_of(e).get("date"))
        if d:
            good.append((d, stp.get("state"), e))
    live = [g for g in good if g[1] == "in"]
    if live:
        return live[0][2]
    pre = sorted((g for g in good if g[1] == "pre"), key=lambda g: g[0])
    post = sorted((g for g in good if g[1] == "post"), key=lambda g: g[0], reverse=True)
    soon = bool(pre) and (pre[0][0] - now) < timedelta(minutes=90)
    if post and not soon and (now - post[0][0]) < timedelta(hours=POST_HOLD_HOURS):
        return post[0][2]
    if pre:
        return pre[0][2]
    if post:
        return post[0][2]
    return None


# -------------------------------------------------------------------- MQTT
def mqtt_settings():
    host = (OPTS.get("mqtt_host") or "").strip()
    if host:
        return (host, int(OPTS.get("mqtt_port") or 1883),
                OPTS.get("mqtt_username") or None, OPTS.get("mqtt_password") or None)
    tok = os.environ.get("SUPERVISOR_TOKEN")
    if tok:
        try:
            req = urllib.request.Request("http://supervisor/services/mqtt",
                                         headers={"Authorization": "Bearer " + tok})
            with urllib.request.urlopen(req, timeout=10) as r:
                d = json.loads(r.read().decode())["data"]
            return d["host"], int(d["port"]), d.get("username"), d.get("password")
        except Exception as e:
            log("warning", "Supervisor MQTT lookup failed:", e)
    return None


def pub(topic, payload, retain=True):
    if CLIENT and MQTT_OK:
        CLIENT.publish(topic, payload, qos=1, retain=retain)


def publish_discovery():
    with LOCK:
        name = S["sensor_name"]
        favs = list(S["favorites"])
    device = {"identifiers": ["team_tracker_lite"], "name": "Team Tracker Lite",
              "manufacturer": "Home-built", "model": "Team Tracker Lite"}
    pub(D_SENSOR, json.dumps({
        "name": name,
        "unique_id": "team_tracker_lite_main",
        "default_entity_id": "sensor." + slug(name),
        "state_topic": T_STATE,
        "json_attributes_topic": T_ATTR,
        "availability_topic": T_AVAIL,
        "icon": "mdi:scoreboard",
        "device": device,
    }))
    if OPTS.get("publish_team_selector") and favs:
        pub(D_SELECT, json.dumps({
            "name": name + " Team",
            "unique_id": "team_tracker_lite_select",
            "default_entity_id": "select." + slug(name) + "_team",
            "command_topic": T_SEL_SET,
            "state_topic": T_SEL_STATE,
            "availability_topic": T_AVAIL,
            "options": [f["label"] for f in favs],
            "icon": "mdi:swap-horizontal",
            "device": device,
        }))
        publish_select_state()
    else:
        pub(D_SELECT, "")  # removes the select if it was ever created


def publish_select_state():
    f = active_fav()
    if f:
        pub(T_SEL_STATE, f["label"])


def publish_sensor(state, attrs):
    global PREV
    with LOCK:
        LAST.update(state=state, attributes=attrs, at=datetime.now(timezone.utc).isoformat())
        tag = (S.get("active"), state)
    if tag != PREV:
        PREV = tag
        log("info", f"Sensor is now {state}: {attrs.get('team_abbr') or attrs.get('team_name') or '-'} "
                    f"vs {attrs.get('opponent_abbr') or '-'} ({attrs.get('api_message')})")
    else:
        log("debug", f"Sensor {state}: {attrs.get('team_score')}-{attrs.get('opponent_score')}")
    pub(T_STATE, state)
    pub(T_ATTR, json.dumps(attrs, default=str))


def on_connect(client, userdata, flags, reason_code, properties=None):
    global MQTT_OK
    if reason_code.is_failure:
        log("error", "MQTT connect failed:", reason_code)
        return
    MQTT_OK = True
    log("info", "MQTT connected")
    pub(T_AVAIL, "online")
    publish_discovery()
    client.subscribe(T_SEL_SET)
    with LOCK:
        st, at = LAST["state"], LAST["attributes"]
    pub(T_STATE, st)
    pub(T_ATTR, json.dumps(at, default=str))


def on_disconnect(client, userdata, flags, reason_code, properties=None):
    global MQTT_OK
    MQTT_OK = False
    log("warning", "MQTT disconnected:", reason_code)


def on_message(client, userdata, msg):
    if msg.topic != T_SEL_SET:
        return
    label = msg.payload.decode("utf-8", "ignore")
    with LOCK:
        for f in S["favorites"]:
            if f["label"] == label:
                S["active"] = f["key"]
                save_settings()
                break
        else:
            return
    publish_select_state()
    WAKE.set()


def mqtt_start():
    global CLIENT
    cfg = mqtt_settings()
    if not cfg:
        log("error", "No MQTT broker configured - set mqtt_host in the add-on Configuration tab")
        return
    host, port, user, pw = cfg
    log("info", f"MQTT broker: {host}:{port}")
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="team_tracker_lite")
    if user:
        c.username_pw_set(user, pw)
    c.will_set(T_AVAIL, "offline", qos=1, retain=True)
    c.on_connect, c.on_disconnect, c.on_message = on_connect, on_disconnect, on_message
    c.on_log = lambda cl, ud, lvl, buf: log("debug", "paho:", buf)
    c.reconnect_delay_set(min_delay=2, max_delay=60)
    CLIENT = c
    c.connect_async(host, port, keepalive=60)
    c.loop_start()


# ------------------------------------------------------------------ polling
def poll_once():
    with LOCK:
        IDLE, LIVE = S["idle_minutes"] * 60, S["live_seconds"]
    fav = active_fav()
    if not fav:
        publish_sensor("NOT_FOUND", {"api_message": "No team selected. Open the Team Tracker panel and pick one."})
        return IDLE
    lid, tid = fav["league"], fav["team_id"]
    now = datetime.now(timezone.utc)
    events = fetch_schedule(lid, tid)
    ev = pick_event(events, now)
    if not ev:
        publish_sensor("NOT_FOUND", {"team_name": fav["name"], "team_abbr": fav["abbr"],
                                     "team_logo": fav["logo"], "league_id": lid,
                                     "api_message": "No games found for this team right now",
                                     "last_update": now.isoformat()})
        return IDLE

    st = state_of(ev)
    when = parse_dt(ev.get("date") or comp_of(ev).get("date"))
    wait = IDLE
    hot = st == "in" or (st == "pre" and when and timedelta(hours=-3) < (when - now) <= timedelta(minutes=10))
    if hot:
        wait = LIVE
        try:
            fresh = fetch_scoreboard_event(lid, ev.get("id"))
            if fresh:
                ev = fresh
                if state_of(fresh) == "post":
                    wait = 120
        except Exception as e:
            log("warning", "Live scoreboard fetch failed, using schedule data:", e)
    elif st == "pre" and when:
        secs = (when - now).total_seconds() - 600
        wait = int(min(IDLE, max(LIVE, secs)))

    built = build(ev, tid, lid)
    if not built:
        publish_sensor("NOT_FOUND", {"api_message": "Team not found in the game data", "last_update": now.isoformat()})
        return IDLE
    publish_sensor(*built)
    return wait


def poll_loop():
    while True:
        WAKE.clear()
        try:
            wait = poll_once()
        except Exception as e:
            log("error", "Poll failed:", e)
            publish_sensor("NOT_FOUND", {"api_message": f"ESPN request failed: {e}"})
            wait = 60
        log("debug", f"Next check in {wait}s")
        WAKE.wait(wait)


# --------------------------------------------------------------- web server
class Handler(BaseHTTPRequestHandler):
    server_version = "TeamTrackerLite/0.1"

    def log_message(self, fmt, *a):
        log("debug", "http", fmt % a)

    def send_body(self, code, body, ctype="application/json"):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(b)

    def allowed(self):
        if ALLOW_ANY or self.client_address[0] in ("172.30.32.2", "127.0.0.1"):
            return True
        self.send_body(403, {"error": "forbidden"})
        return False

    def state_payload(self):
        with LOCK:
            return {"settings": json.loads(json.dumps(S)), "sensor": dict(LAST),
                    "mqtt": MQTT_OK, "selector": bool(OPTS.get("publish_team_selector"))}

    def do_GET(self):
        if not self.allowed():
            return
        u = urllib.parse.urlparse(self.path)
        p = "/" + u.path.strip("/")
        qs = urllib.parse.parse_qs(u.query)
        if p in ("/", "/index.html"):
            with open(os.path.join(HERE, "index.html"), "rb") as f:
                return self.send_body(200, f.read(), "text/html; charset=utf-8")
        if p == "/api/leagues":
            return self.send_body(200, [{"id": k, "label": v[0]} for k, v in LEAGUES.items()])
        if p == "/api/teams":
            lid = (qs.get("league") or [""])[0]
            if lid not in LEAGUES:
                return self.send_body(400, {"error": "unknown league"})
            try:
                return self.send_body(200, get_teams(lid))
            except Exception as e:
                return self.send_body(502, {"error": f"ESPN request failed: {e}"})
        if p == "/api/state":
            return self.send_body(200, self.state_payload())
        self.send_body(404, {"error": "not found"})

    def do_POST(self):
        if not self.allowed():
            return
        p = "/" + urllib.parse.urlparse(self.path).path.strip("/")
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self.send_body(400, {"error": "bad json"})

        if p == "/api/favorites":
            lid, tid = body.get("league"), str(body.get("team_id") or "")
            if lid not in LEAGUES or not tid:
                return self.send_body(400, {"error": "league and team_id required"})
            key = f"{lid}:{tid}"
            name = str(body.get("name") or tid)[:80]
            with LOCK:
                if not any(f["key"] == key for f in S["favorites"]):
                    S["favorites"].append({
                        "key": key, "league": lid, "team_id": tid,
                        "abbr": str(body.get("abbr") or "")[:10], "name": name,
                        "logo": str(body.get("logo") or "")[:300], "label": f"{lid} {name}",
                    })
                    log("info", f"Added team: {name} ({lid})")
                if not S["active"]:
                    S["active"] = key
                save_settings()
        elif p == "/api/active":
            with LOCK:
                if not any(f["key"] == body.get("key") for f in S["favorites"]):
                    return self.send_body(400, {"error": "unknown team"})
                S["active"] = body["key"]
                save_settings()
            log("info", "Now tracking", body["key"])
        elif p == "/api/remove":
            with LOCK:
                S["favorites"] = [f for f in S["favorites"] if f["key"] != body.get("key")]
                if S["active"] == body.get("key"):
                    S["active"] = S["favorites"][0]["key"] if S["favorites"] else None
                save_settings()
            log("info", "Removed team", body.get("key"))
        elif p == "/api/name":
            name = str(body.get("name") or "").strip()[:60]
            if not name:
                return self.send_body(400, {"error": "name required"})
            with LOCK:
                S["sensor_name"] = name
                save_settings()
            log("info", "Sensor renamed to", name)
        elif p == "/api/rates":
            with LOCK:
                S["idle_minutes"] = clamp(body.get("idle_minutes"), 1, 60, S["idle_minutes"])
                S["live_seconds"] = clamp(body.get("live_seconds"), 5, 120, S["live_seconds"])
                save_settings()
            log("info", f"Refresh speed: every {S['idle_minutes']} min idle, {S['live_seconds']}s during games")
        elif p == "/api/refresh":
            pass
        else:
            return self.send_body(404, {"error": "not found"})

        publish_discovery()
        WAKE.set()
        self.send_body(200, self.state_payload())


def main():
    global OPTS, S, LOG_LEVEL
    OPTS = load_json(OPTIONS_FILE, {})
    LOG_LEVEL = LEVELS.get(str(OPTS.get("log_level") or "info").lower(), 20)
    init_storage()
    S = load_settings()
    log("info", f"Team Tracker Lite {VERSION} starting (log level: {OPTS.get('log_level') or 'info'})")
    log("info", f"Settings file: {SETTINGS_FILE} ({len(S['favorites'])} saved teams)")
    log("info", f"Refresh: every {S['idle_minutes']} min idle, {S['live_seconds']}s during games")
    mqtt_start()
    threading.Thread(target=poll_loop, daemon=True).start()
    log("info", "Web UI on port 8099")
    ThreadingHTTPServer(("0.0.0.0", 8099), Handler).serve_forever()


if __name__ == "__main__":
    main()
