import datetime as dt
import json
import os
import threading
import time
from zoneinfo import ZoneInfo

import paho.mqtt.client as mqtt
import requests
from flask import Flask, jsonify, request, send_from_directory

DATA = "/data"
TRACK_FILE = f"{DATA}/tracked.json"
SET_FILE = f"{DATA}/settings.json"
DISC_FILE = f"{DATA}/discovered_people.json"
SUP = "http://supervisor"
SUP_HEADERS = {"Authorization": "Bearer " + os.environ.get("SUPERVISOR_TOKEN", "")}
TMDB = "https://api.themoviedb.org/3"

DEFAULTS = {
    "tmdb_key": "",
    "region": "US",
    "refresh_hours": 6,
    "window_days": 60,
    "people": ["Jon", "MJ"],
    "mqtt_host": "",
    "mqtt_port": 1883,
    "mqtt_user": "",
    "mqtt_pass": "",
    "igdb_id": "",
    "igdb_secret": "",
}
SECRETS = ("tmdb_key", "mqtt_pass", "igdb_secret")

lock = threading.RLock()
app = Flask(__name__, static_folder="static")


# ---------- storage ----------
def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def save(path, data):
    with lock:
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, path)


def settings():
    s = dict(DEFAULTS)
    s.update(load(SET_FILE, {}))
    return s


def get_tz():
    try:
        r = requests.get(f"{SUP}/info", headers=SUP_HEADERS, timeout=10)
        return ZoneInfo(r.json()["data"]["timezone"])
    except Exception:
        return ZoneInfo("America/New_York")


TZ = get_tz()


def today():
    return dt.datetime.now(TZ).date()


# ---------- TMDB ----------
def tmdb(path, **params):
    key = settings()["tmdb_key"].strip()
    if not key:
        raise RuntimeError("Add your TMDB key in Settings first")
    headers = {}
    if key.startswith("eyJ"):  # v4 read-access token
        headers["Authorization"] = f"Bearer {key}"
    else:
        params["api_key"] = key
    r = requests.get(f"{TMDB}{path}", params=params, headers=headers, timeout=15)
    r.raise_for_status()
    return r.json()


# ---------- IGDB (video games) ----------
IGDB = "https://api.igdb.com/v4"
IGDB_IMG = "https://images.igdb.com/igdb/image/upload/t_cover_big/"
GAME_FIELDS = (
    "name,cover.image_id,game_type.type,first_release_date,"
    "release_dates.date,release_dates.date_format,release_dates.human"
)
MAIN_KINDS = ("Main Game", "Game", "Remake", "Remaster", "Port", "Expanded Game")
_igdb_tok = {"token": None, "exp": 0, "creds": None}


def games_ready(s=None):
    s = s or settings()
    return bool(s["igdb_id"].strip() and s["igdb_secret"].strip())


def igdb_token(force=False):
    s = settings()
    cid, sec = s["igdb_id"].strip(), s["igdb_secret"].strip()
    if not cid or not sec:
        raise RuntimeError("Add your Twitch Client ID and Secret in Settings first")
    t = _igdb_tok
    if not force and t["token"] and t["creds"] == (cid, sec) and time.time() < t["exp"]:
        return cid, t["token"]
    r = requests.post(
        "https://id.twitch.tv/oauth2/token",
        params={"client_id": cid, "client_secret": sec, "grant_type": "client_credentials"},
        timeout=15,
    )
    if r.status_code in (400, 401, 403):
        raise RuntimeError("Twitch rejected the Client ID or Secret. Check them in Settings.")
    r.raise_for_status()
    j = r.json()
    t.update(token=j["access_token"], exp=time.time() + int(j.get("expires_in", 3600)) - 300, creds=(cid, sec))
    return cid, t["token"]


def igdb(endpoint, query):
    for attempt in (0, 1):
        cid, token = igdb_token(force=attempt == 1)
        r = requests.post(
            f"{IGDB}/{endpoint}",
            data=query,
            headers={"Client-ID": cid, "Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=15,
        )
        if r.status_code == 401 and attempt == 0:
            continue  # token expired, get a fresh one and retry once
        r.raise_for_status()
        return r.json()


def utc_date(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat()


def game_dates(g):
    """Exact dates (ISO strings) for one game, plus a vague text like 'Q2 2027' if that is all we have."""
    exact, vague = [], []
    for rd in g.get("release_dates") or []:
        ts = rd.get("date")
        if not ts:
            continue
        if rd.get("date_format", 0) == 0:
            exact.append(utc_date(ts))
        elif rd.get("human") and rd["human"] != "TBD":
            vague.append((ts, rd["human"]))
    if not exact and not vague and g.get("first_release_date"):
        exact.append(utc_date(g["first_release_date"]))
    return exact, (sorted(vague)[0][1] if vague else None)


def fetch_game(item):
    gid = int(item["id"])
    rows = igdb("games", f"fields {GAME_FIELDS},dlcs,expansions,standalone_expansions; where id = {gid};")
    if not rows:
        raise RuntimeError("Game not found on IGDB")
    g = rows[0]
    kind = (g.get("game_type") or {}).get("type") or "Game"
    kid_ids = sorted(set((g.get("dlcs") or []) + (g.get("expansions") or []) + (g.get("standalone_expansions") or [])))
    kids = []
    if kid_ids:
        ids = ",".join(str(i) for i in kid_ids[:100])
        kids = igdb("games", f"fields {GAME_FIELDS}; where id = ({ids}); limit 100;")

    pieces = [(g, "Release" if kind in MAIN_KINDS else f"{kind} release")]
    for k in kids:
        kk = (k.get("game_type") or {}).get("type") or "DLC"
        pieces.append((k, f"{kk}: {k.get('name')}"))

    now = today().isoformat()
    upcoming_ev, vague_ev, past_ev = [], [], []
    for game, label in pieces:
        exact, vague = game_dates(game)
        future = [d for d in exact if d >= now]
        if future:
            upcoming_ev.append((min(future), label))
        elif vague:
            vague_ev.append(f"{label} - expected {vague}")
        elif exact:
            past_ev.append((max(exact), label))
    upcoming_ev.sort()

    cover = (g.get("cover") or {}).get("image_id")
    info = {
        "title": g.get("name"),
        "poster": (IGDB_IMG + cover + ".jpg") if cover else None,
        "status": kind,
        "all_dates": [{"date": d, "label": l} for d, l in upcoming_ev],
    }
    if upcoming_ev:
        info["next_date"], info["label"] = upcoming_ev[0]
    elif vague_ev:
        info["next_date"], info["label"] = None, vague_ev[0]
    elif past_ev:
        info["next_date"], info["label"] = None, f"Already out ({max(past_ev)[0]})"
    else:
        info["next_date"], info["label"] = None, "No date announced yet"
    return info


def search_games(q):
    q = q.replace('"', " ").replace("\\", " ")
    rows = igdb(
        "games",
        f'search "{q}"; fields name,cover.image_id,first_release_date,game_type.type; '
        "where version_parent = null; limit 15;",
    )
    out = []
    for r in rows:
        cover = (r.get("cover") or {}).get("image_id")
        out.append({
            "id": r["id"], "type": "game", "title": r.get("name"),
            "kind": (r.get("game_type") or {}).get("type") or "Game",
            "year": utc_date(r["first_release_date"])[:4] if r.get("first_release_date") else "",
            "poster": (IGDB_IMG + cover + ".jpg") if cover else None,
            "overview": "",
        })
    return out


MOVIE_TYPES = {2: "In theaters", 3: "In theaters", 4: "Digital release", 5: "Physical release"}


def fetch_info(item):
    if item["type"] == "game":
        return fetch_game(item)
    s = settings()
    now = today().isoformat()
    if item["type"] == "movie":
        d = tmdb(f"/movie/{item['id']}", append_to_response="release_dates")
        found = {}
        for c in d.get("release_dates", {}).get("results", []):
            if c.get("iso_3166_1") != s["region"]:
                continue
            for rd in c.get("release_dates", []):
                label = MOVIE_TYPES.get(rd.get("type"))
                day = (rd.get("release_date") or "")[:10]
                if label and day and (label not in found or day < found[label]):
                    found[label] = day
        if not found and d.get("release_date"):
            found["Release"] = d["release_date"]
        events = sorted((day, label) for label, day in found.items())
        future = [e for e in events if e[0] >= now]
        info = {
            "title": d.get("title"),
            "poster": d.get("poster_path"),
            "status": d.get("status"),
            "all_dates": [{"date": a, "label": b} for a, b in events],
        }
        if future:
            info["next_date"], info["label"] = future[0]
        elif events:
            info["next_date"], info["label"] = None, f"Already out ({events[-1][0]})"
        else:
            info["next_date"], info["label"] = None, "No date announced yet"
        return info

    d = tmdb(f"/tv/{item['id']}")
    n = d.get("next_episode_to_air")
    info = {"title": d.get("name"), "poster": d.get("poster_path"), "status": d.get("status")}
    if n and n.get("air_date"):
        if n.get("episode_number") == 1:
            label = f"Season {n.get('season_number')} premiere"
        else:
            label = f"S{n.get('season_number')}E{n.get('episode_number')}"
            if n.get("name"):
                label += f" - {n['name']}"
        info["next_date"], info["label"] = n["air_date"], label
    else:
        info["next_date"] = None
        info["label"] = {
            "Returning Series": "No date announced yet",
            "Ended": "Ended",
            "Canceled": "Canceled",
            "In Production": "In production",
            "Planned": "Planned",
        }.get(d.get("status"), d.get("status") or "Unknown")
    return info


def refresh_all():
    tracked = load(TRACK_FILE, [])
    results = {}
    for it in tracked:
        try:
            results[(it["type"], it["id"])] = (fetch_info(it), None)
        except Exception as e:
            results[(it["type"], it["id"])] = (None, str(e))
    with lock:
        current = load(TRACK_FILE, [])
        for it in current:
            res = results.get((it["type"], it["id"]))
            if res:
                if res[0]:
                    it["info"] = res[0]
                it["error"] = res[1]
        save(TRACK_FILE, current)
    publish()


# ---------- derived data ----------
def days_until(date_str):
    return (dt.date.fromisoformat(date_str) - today()).days


def upcoming(games=False):
    rows = []
    for it in load(TRACK_FILE, []):
        if (it["type"] == "game") != games:
            continue
        info = it.get("info") or {}
        nd = info.get("next_date")
        if not nd:
            continue
        d = days_until(nd)
        if d < 0:
            continue
        rows.append(
            {
                "title": info.get("title") or it["title"],
                "type": {"movie": "Movie", "game": "Game"}.get(it["type"], "TV"),
                "date": nd,
                "days_until": d,
                "label": info.get("label"),
                "people": it.get("people", []),
            }
        )
    rows.sort(key=lambda r: (r["date"], r["title"]))
    return rows


# ---------- MQTT ----------
client = None
_sent = {}
T_STATUS = "release_tracker/status"
T = {k: f"release_tracker/{k}" for k in ("next", "upcoming", "today", "games")}
DEVICE = {
    "identifiers": ["release_tracker"],
    "name": "Release Tracker",
    "manufacturer": "Jon",
    "model": "Release Tracker add-on",
}


def mqtt_conf():
    s = settings()
    if s["mqtt_host"]:
        return s["mqtt_host"], int(s["mqtt_port"] or 1883), s["mqtt_user"], s["mqtt_pass"]
    try:
        r = requests.get(f"{SUP}/services/mqtt", headers=SUP_HEADERS, timeout=10)
        r.raise_for_status()
        d = r.json()["data"]
        return d["host"], int(d["port"]), d.get("username"), d.get("password")
    except Exception as e:
        print(f"[mqtt] no broker info from Home Assistant: {e}", flush=True)
        return None


def pub(topic, payload):
    if client is None:
        return
    text = payload if isinstance(payload, str) else json.dumps(payload)
    if _sent.get(topic) == text:
        return
    _sent[topic] = text
    client.publish(topic, text, retain=True)


def send_discovery(c):
    common = {"device": DEVICE, "availability_topic": T_STATUS}
    ents = [
        ("sensor", "next", {
            "name": "Next Release", "icon": "mdi:movie-open-play",
            "state_topic": T["next"], "value_template": "{{ value_json.state }}",
            "json_attributes_topic": T["next"],
            "json_attributes_template": "{{ value_json.attributes | tojson }}"}),
        ("sensor", "upcoming", {
            "name": "Upcoming Releases", "icon": "mdi:calendar-star",
            "state_topic": T["upcoming"], "value_template": "{{ value_json.state }}",
            "json_attributes_topic": T["upcoming"],
            "json_attributes_template": "{{ value_json.attributes | tojson }}"}),
        ("binary_sensor", "today", {
            "name": "Releasing Today", "icon": "mdi:party-popper",
            "state_topic": T["today"], "value_template": "{{ value_json.state }}",
            "payload_on": "ON", "payload_off": "OFF",
            "json_attributes_topic": T["today"],
            "json_attributes_template": "{{ value_json.attributes | tojson }}"}),
        ("sensor", "games", {
            "name": "Upcoming Games", "icon": "mdi:controller",
            "state_topic": T["games"], "value_template": "{{ value_json.state }}",
            "json_attributes_topic": T["games"],
            "json_attributes_template": "{{ value_json.attributes | tojson }}"}),
    ]
    for comp, key, cfg in ents:
        cfg.update(common)
        cfg["unique_id"] = f"release_tracker_{key}"
        c.publish(f"homeassistant/{comp}/release_tracker/{key}/config", json.dumps(cfg), retain=True)


_disc_people = None


def slug(name):
    out = "".join(ch if ch.isalnum() else "_" for ch in name.lower()).strip("_")
    return out or "person"


def people_list():
    people = {}
    for p in settings().get("people", []):
        p = str(p).strip()
        if p and slug(p) not in people:
            people[slug(p)] = p
    return people


def person_topic(sl, key):
    return f"release_tracker/person/{sl}/{key}"


def sync_people_discovery():
    global _disc_people
    if client is None:
        return
    want = people_list()
    if _disc_people == set(want):
        return
    old = set(load(DISC_FILE, [])) | (_disc_people or set())
    for sl in old - set(want):
        client.publish(f"homeassistant/sensor/release_tracker/p_{sl}_upcoming/config", "", retain=True)
        client.publish(f"homeassistant/binary_sensor/release_tracker/p_{sl}_today/config", "", retain=True)
    common = {"device": DEVICE, "availability_topic": T_STATUS}
    for sl, name in want.items():
        up = {
            "name": f"{name} Upcoming", "icon": "mdi:account-clock",
            "unique_id": f"release_tracker_p_{sl}_upcoming",
            "state_topic": person_topic(sl, "upcoming"), "value_template": "{{ value_json.state }}",
            "json_attributes_topic": person_topic(sl, "upcoming"),
            "json_attributes_template": "{{ value_json.attributes | tojson }}", **common}
        td = {
            "name": f"{name} Releasing Today", "icon": "mdi:bell-ring",
            "unique_id": f"release_tracker_p_{sl}_today",
            "state_topic": person_topic(sl, "today"), "value_template": "{{ value_json.state }}",
            "payload_on": "ON", "payload_off": "OFF",
            "json_attributes_topic": person_topic(sl, "today"),
            "json_attributes_template": "{{ value_json.attributes | tojson }}", **common}
        client.publish(f"homeassistant/sensor/release_tracker/p_{sl}_upcoming/config", json.dumps(up), retain=True)
        client.publish(f"homeassistant/binary_sensor/release_tracker/p_{sl}_today/config", json.dumps(td), retain=True)
    save(DISC_FILE, sorted(want))
    _disc_people = set(want)


def publish():
    rows = upcoming()
    s = settings()
    tracked = load(TRACK_FILE, [])
    window = [r for r in rows if r["days_until"] <= int(s["window_days"])]
    if rows:
        n = rows[0]
        pub(T["next"], {"state": n["title"], "attributes": {
            "date": n["date"], "days_until": n["days_until"], "label": n["label"], "type": n["type"]}})
    else:
        pub(T["next"], {"state": "Nothing scheduled", "attributes": {
            "date": None, "days_until": None, "label": None, "type": None}})
    pub(T["upcoming"], {"state": len(window), "attributes": {
        "items": window[:25], "window_days": int(s["window_days"]),
        "tracked_count": len([t for t in tracked if t["type"] != "game"])}})
    grows = upcoming(games=True)
    gwin = [r for r in grows if r["days_until"] <= int(s["window_days"])]
    gn = grows[0] if grows else {}
    pub(T["games"], {"state": len(gwin), "attributes": {
        "items": gwin[:25], "window_days": int(s["window_days"]),
        "tracked_count": len([t for t in tracked if t["type"] == "game"]),
        "next_title": gn.get("title"), "next_date": gn.get("date"),
        "next_days_until": gn.get("days_until"), "next_label": gn.get("label")}})
    now = [r for r in rows if r["days_until"] == 0]
    people = people_list()
    pub(T["today"], {"state": "ON" if now else "OFF", "attributes": {
        "titles": [r["title"] for r in now], "items": now,
        "by_person": {name: [r["title"] for r in now if name in r["people"]] for name in people.values()}}})
    sync_people_discovery()
    w = int(s["window_days"])
    for sl, name in people.items():
        mine = [r for r in rows if name in r["people"]]
        soon = [r for r in mine if r["days_until"] <= w]
        pub(person_topic(sl, "upcoming"), {"state": len(soon), "attributes": {
            "person": name, "items": soon[:25]}})
        todays = [r for r in mine if r["days_until"] == 0]
        pub(person_topic(sl, "today"), {"state": "ON" if todays else "OFF", "attributes": {
            "person": name, "titles": [r["title"] for r in todays], "items": todays}})


def on_connect(c, userdata, flags, reason_code, properties=None):
    print(f"[mqtt] connected: {reason_code}", flush=True)
    global _disc_people
    _sent.clear()
    _disc_people = None
    send_discovery(c)
    c.publish(T_STATUS, "online", retain=True)
    publish()


def connect_mqtt():
    global client
    if client is not None:
        try:
            client.publish(T_STATUS, "offline", retain=True)
            client.loop_stop()
            client.disconnect()
        except Exception:
            pass
        client = None
    conf = mqtt_conf()
    if not conf:
        return
    host, port, user, pw = conf
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="release_tracker_addon")
    if user:
        c.username_pw_set(user, pw)
    c.will_set(T_STATUS, "offline", retain=True)
    c.on_connect = on_connect
    client = c
    try:
        c.connect_async(host, port, 60)
        c.loop_start()
    except Exception as e:
        print(f"[mqtt] connect failed: {e}", flush=True)


# ---------- background worker ----------
def worker():
    last = 0
    while True:
        try:
            s = settings()
            if client is None:
                connect_mqtt()
            due = time.time() - last >= max(1, float(s["refresh_hours"])) * 3600
            if due and (s["tmdb_key"] or games_ready(s)):
                refresh_all()
                last = time.time()
            else:
                publish()  # keeps "days until" correct at midnight
        except Exception as e:
            print(f"[worker] {e}", flush=True)
        time.sleep(60)


# ---------- web API ----------
@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/state")
def api_state():
    s = settings()
    tracked = load(TRACK_FILE, [])
    for it in tracked:
        nd = (it.get("info") or {}).get("next_date")
        it["days_until"] = days_until(nd) if nd else None
    safe = {k: v for k, v in s.items() if k not in SECRETS}
    safe["has_key"] = bool(s["tmdb_key"])
    safe["has_mqtt_pass"] = bool(s["mqtt_pass"])
    safe["has_games_key"] = games_ready(s)
    safe["has_igdb_secret"] = bool(s["igdb_secret"])
    return jsonify({"settings": safe, "tracked": tracked, "mqtt": client is not None})


@app.route("/api/search")
def api_search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    if request.args.get("kind") == "games":
        try:
            return jsonify(search_games(q))
        except Exception as e:
            return jsonify({"error": str(e)}), 400
    try:
        res = tmdb("/search/multi", query=q, include_adult="false")
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    out = []
    for r in res.get("results", []):
        if r.get("media_type") not in ("movie", "tv"):
            continue
        out.append({
            "id": r["id"], "type": r["media_type"],
            "title": r.get("title") or r.get("name"),
            "year": (r.get("release_date") or r.get("first_air_date") or "")[:4],
            "poster": r.get("poster_path"),
            "overview": (r.get("overview") or "")[:140],
        })
    return jsonify(out[:12])


def clean_people(v):
    if isinstance(v, str):
        v = v.split(",")
    return [str(p).strip() for p in (v or []) if str(p).strip()]


@app.route("/api/track/<media_type>/<int:tid>/people", methods=["PUT"])
def api_set_people(media_type, tid):
    people = clean_people(request.get_json(force=True).get("people"))
    with lock:
        tracked = load(TRACK_FILE, [])
        for t in tracked:
            if t["id"] == tid and t["type"] == media_type:
                t["people"] = people
        save(TRACK_FILE, tracked)
    publish()
    return jsonify({"ok": True})


@app.route("/api/track", methods=["POST"])
def api_track():
    b = request.get_json(force=True)
    if b.get("type") not in ("movie", "tv", "game"):
        return jsonify({"error": "Unknown type"}), 400
    item = {"id": int(b["id"]), "type": b["type"], "title": b.get("title", ""), "poster": b.get("poster"),
            "people": [] if b["type"] == "game" else clean_people(b.get("people"))}
    with lock:
        tracked = load(TRACK_FILE, [])
        for t in tracked:
            if t["id"] == item["id"] and t["type"] == item["type"]:
                t["people"] = sorted(set(t.get("people", [])) | set(item["people"]))
                save(TRACK_FILE, tracked)
                publish()
                return jsonify({"ok": True})
        try:
            item["info"] = fetch_info(item)
        except Exception as e:
            item["error"] = str(e)
        tracked.append(item)
        save(TRACK_FILE, tracked)
    publish()
    return jsonify({"ok": True})


@app.route("/api/track/<media_type>/<int:tid>", methods=["DELETE"])
def api_untrack(media_type, tid):
    with lock:
        tracked = [t for t in load(TRACK_FILE, []) if not (t["id"] == tid and t["type"] == media_type)]
        save(TRACK_FILE, tracked)
    publish()
    return jsonify({"ok": True})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    refresh_all()
    return jsonify({"ok": True})


@app.route("/api/settings", methods=["POST"])
def api_settings():
    b = request.get_json(force=True)
    s = settings()
    for k in DEFAULTS:
        if k not in b:
            continue
        if k in SECRETS and not str(b[k]).strip():
            continue  # blank = keep the saved one
        s[k] = clean_people(b[k]) if k == "people" else b[k]
    save(SET_FILE, s)
    threading.Thread(target=connect_mqtt, daemon=True).start()
    threading.Thread(target=refresh_all, daemon=True).start()
    return jsonify({"ok": True})


if __name__ == "__main__":
    os.makedirs(DATA, exist_ok=True)
    threading.Thread(target=worker, daemon=True).start()
    app.run(host="0.0.0.0", port=8099, threaded=True)
