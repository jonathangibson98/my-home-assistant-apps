import asyncio, datetime, json, os, re, shutil, time, urllib.request
import yaml
import paho.mqtt.client as mqtt
from aiohttp import web

DIR = "/homeassistant/ai_memory"
FILE = f"{DIR}/people.yaml"          # household, friends, other
MUSIC_FILE = f"{DIR}/music.yaml"     # music lives in its own file now
PLACES_FILE = f"{DIR}/places.yaml"   # places (addresses, workplaces) live here
SRC = f"{DIR}/memory/merged.yaml"
BAK = f"{DIR}/backups"
SETTINGS_PATH = "/data/settings.json"
KEYS = ("household", "friends", "music", "other")
BASE = "personalized_info"
DEFAULTS = {"info": "Personalized Info", "music": "Personalized Music"}
ICONS = {"info": "mdi:account-group", "music": "mdi:music"}

OPT = json.load(open("/data/options.json"))
CORE = [str(p).lower() for p in OPT.get("core_people", [])]
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")

def slug(t):
    return re.sub(r"[^a-z0-9]+", "_", str(t).lower()).strip("_")

# ---------- settings: names editable in UI, IDs permanent ----------
def save_settings(d):
    with open(SETTINGS_PATH, "w") as f:
        json.dump(d, f, indent=2)

def load_settings():
    data = {}
    try:
        data = json.load(open(SETTINGS_PATH))
    except Exception:
        pass
    changed = False
    for key, default in DEFAULTS.items():
        s = data.setdefault(key, {})
        if not s.get("name"):
            s["name"] = default; changed = True
        if not s.get("unique_id"):
            s["unique_id"] = f"{BASE}_{key}"; changed = True
        if not s.get("entity_id"):
            # fixed at creation; renaming later only changes the display name
            s["entity_id"] = "sensor." + slug(s["name"]); changed = True
    if changed:
        save_settings(data)
    return data

SET = load_settings()

# ---------- data files ----------
def flat(o):
    if isinstance(o, dict):
        return [x for v in o.values() for x in flat(v)]
    if isinstance(o, list):
        return [x for v in o for x in flat(v)]
    return [] if o is None else [str(o)]

def import_merged():
    data = {k: {} for k in KEYS}
    try:
        raw = open(SRC).read()
    except Exception:
        return data
    parts = re.split(r"^===\s*(.+?)\s*===\s*$", raw, flags=re.M)
    for i in range(1, len(parts), 2):
        name = slug(parts[i])
        block = parts[i + 1] if i + 1 < len(parts) else ""
        lines = [l for l in block.splitlines()
                 if not (l.strip().startswith("-----") and l.strip().endswith("-----"))
                 and not l.strip().startswith("Updated:")]
        try:
            c = yaml.safe_load("\n".join(lines)) or {}
        except Exception:
            c = {}
        if "favorite" in name:
            m = data["music"].setdefault("shared", {"genres": [], "artists": []})
            m["artists"] = sorted(set(m["artists"] + flat(c)), key=str.lower)
        elif name == "household_info" and isinstance(c, dict):
            data["household"].update(c)
        elif name == "friends_info" and isinstance(c, dict):
            data["friends"].update(c)
        else:
            data["other"][name] = c
    for g in ("household", "friends"):
        for k, p in data[g].items():
            if isinstance(p, dict) and "music" in p:
                m = p.pop("music")
                if isinstance(m, dict):
                    data["music"][k] = {
                        "genres": flat(m.get("genres", [])),
                        "artists": flat(m.get("artists", m.get("favorite_artists", []))),
                    }
                else:
                    data["music"][k] = {"genres": [], "artists": flat(m)}
    return data

def write_yaml(path, data, header):
    """Write a yaml file safely, keeping the last 20 backups of that file."""
    os.makedirs(BAK, exist_ok=True)
    stem = os.path.basename(path)[:-5]  # "people" or "music"
    if os.path.exists(path):
        shutil.copy(path, f"{BAK}/{stem}-{time.strftime('%Y%m%d-%H%M%S')}.yaml")
        mine = sorted(f for f in os.listdir(BAK) if f.startswith(stem + "-"))
        for old in mine[:-5]:
            os.remove(f"{BAK}/{old}")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(header)
        yaml.dump(data, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
    os.replace(tmp, path)

def save(d):
    write_yaml(FILE, {k: d.get(k, {}) for k in ("household", "friends", "other")},
               "# Edited via the Personalized Info app. Safe to hand-edit.\n")
    write_yaml(MUSIC_FILE, d.get("music", {}),
               "# Music for the Personalized Music sensor. Safe to hand-edit.\n")
    if "places" in d:  # an older web page won't send places, so don't wipe the file
        write_yaml(PLACES_FILE, d["places"],
                   "# Places that people link to (home, work, hangouts). Safe to hand-edit.\n")

def clean_music(m):
    """Accepts the app's own layout, or the by_person layout from the first conversion."""
    if not isinstance(m, dict):
        return {}
    m = m.get("music", m)
    if isinstance(m, dict) and "by_person" in m:
        out = {"shared": {"genres": [],
                          "artists": flat(m.get("jon_and_mj_favorites", {}).get("artists", []))}}
        for k, v in m["by_person"].items():
            out[k] = {"genres": [g for g in v if g != "other"] if isinstance(v, dict) else [],
                      "artists": flat(v)}
        return out
    return m if isinstance(m, dict) else {}

def fold_music(v):
    """Turn any music shape into (genres, artists)."""
    if isinstance(v, dict):
        if "artists" in v or "genres" in v or "favorite_artists" in v:
            return (flat(v.get("genres", [])),
                    flat(v.get("artists", v.get("favorite_artists", []))))
        return [g for g in v if str(g).lower() != "other"], flat(v)
    return [], flat(v)

def fold_person_music(d):
    """Pull music keys out of people and into d["music"]. True if anything moved."""
    moved = False
    for g in ("household", "friends"):
        for k, p in d[g].items():
            if not isinstance(p, dict):
                continue
            for key in ("top_artists", "music"):
                if key not in p:
                    continue
                genres, artists = fold_music(p.pop(key))
                moved = True
                prof = d["music"].get(k)
                if not isinstance(prof, dict):
                    prof = d["music"][k] = {"genres": [], "artists": []}
                for field, new in (("genres", genres), ("artists", artists)):
                    cur = flat(prof.get(field, []))
                    prof[field] = cur + [x for x in new if x not in cur]
    return moved

def load():
    d = None
    if os.path.exists(FILE):
        try:
            d = yaml.safe_load(open(FILE)) or {}
        except Exception as e:
            print("people.yaml unreadable, re-importing:", e, flush=True)
    if d is None:
        d = import_merged()
        save(d)
        return d
    migrate = False
    if os.path.exists(MUSIC_FILE):
        d.pop("music", None)  # music.yaml is the source of truth now
        try:
            music = clean_music(yaml.safe_load(open(MUSIC_FILE)) or {})
        except Exception as e:
            print("music.yaml unreadable:", e, flush=True)
            music = {}
    else:
        # first run after the update: move music out of people.yaml into music.yaml
        music = clean_music(d.pop("music", None) or {})
        migrate = True
    d["music"] = music
    for k in KEYS:
        d.setdefault(k, {})
    # places live in places.yaml
    if os.path.exists(PLACES_FILE):
        try:
            places = yaml.safe_load(open(PLACES_FILE)) or {}
        except Exception as e:
            print("places.yaml unreadable:", e, flush=True)
            places = {}
    else:
        places, migrate = {}, True
    if not isinstance(places, dict):
        places = {}
    # an old "places" section under other moves into places.yaml
    moved = False
    if "places" in d["other"]:
        legacy = d["other"].pop("places")
        moved = True
        if isinstance(legacy, dict):
            for k, v in legacy.items():
                places.setdefault(k, v)
    d["places"] = places
    # music written inside a person (top_artists / music) moves to the music file
    moved = fold_person_music(d) or moved
    if migrate or moved:
        save(d)
    return d

# ---------- sensor content ----------
def count_facts(o):
    if isinstance(o, dict):
        return sum(count_facts(v) for v in o.values())
    if isinstance(o, list):
        return sum(count_facts(i) for i in o)
    return 1

def to_text(o, depth=0):
    lines, pad = [], "  " * depth
    if isinstance(o, dict):
        for k, v in o.items():
            label = str(k).replace("_", " ")
            if isinstance(v, dict):
                lines.append(f"{pad}{label}:")
                lines.extend(to_text(v, depth + 1))
            elif isinstance(v, list):
                lines.append(f"{pad}{label}: {', '.join(str(i) for i in v)}")
            else:
                lines.append(f"{pad}{label}: {v}")
    return lines

def people_text(people, only=None):
    blocks = []
    for key, data in people.items():
        if only and str(key).lower() not in only:
            continue
        if not isinstance(data, dict):
            continue
        header = str(data.get("name", key)).upper()
        blocks.append("\n".join([header] + to_text(data, 1)))
    return "\n\n".join(blocks)

def pname(d, k):
    p = d["household"].get(k) or d["friends"].get(k)
    return p.get("name", k) if isinstance(p, dict) else k

def person_music(d, k):
    v = d["music"].get(k)
    if not isinstance(v, dict):
        return None
    m = {"genres": flat(v.get("genres", [])), "artists": flat(v.get("artists", []))}
    return m if (m["genres"] or m["artists"]) else None

def prune(o):
    """Drop blank fields so unfilled template fields stay out of the sensor."""
    empty = ("", None, [], {})
    if isinstance(o, dict):
        out = {k: prune(v) for k, v in o.items()}
        return {k: v for k, v in out.items() if v not in empty}
    if isinstance(o, list):
        return [x for x in (prune(i) for i in o) if x not in empty]
    return o

def resolve_places(d, p):
    """Turn a person's place links (label: place key) into the full place info."""
    links = p.get("places")
    if not isinstance(links, dict):
        return None
    out = {}
    for label, key in links.items():
        pl = d["places"].get(key)
        out[label] = {"key": key, **prune(pl)} if isinstance(pl, dict) else {"key": key, "missing": True}
    return out or None

def with_extras(d, group):
    """Copy of a group (household/friends) with each person's music and full place info."""
    out = {}
    for k, p in group.items():
        if not isinstance(p, dict):
            out[k] = p
            continue
        q = dict(p)
        q.pop("places", None)
        pl = resolve_places(d, p)
        if pl:
            q["places"] = pl
        m = person_music(d, k)
        if m:
            q["music"] = m
        out[k] = q
    return out

def build_info(d):
    raw_hh, raw_fr, other = d["household"], d["friends"], d["other"]
    total = count_facts({"household": raw_hh, "friends": raw_fr, **other})
    hh, fr = with_extras(d, raw_hh), with_extras(d, raw_fr)
    now = datetime.datetime.now()
    ts = f"{now.strftime('%m/%d/%y')} - {now.strftime('%I:%M%p').lstrip('0').lower()}"
    everyone = {}
    for k, v in hh.items():
        if isinstance(v, dict):
            everyone[k] = {"group": "household", **v}
    for k, v in fr.items():
        if isinstance(v, dict):
            everyone[k] = {"group": "friends", **v}
    music_by_person = {k: v["music"] for k, v in everyone.items() if "music" in v}
    attrs = {
        "total_facts": total, "last_update": ts,
        "household_count": len(hh), "friends_count": len(fr),
        "sections": ["household", "friends"] + list(other.keys()),
        "household": hh, "friends": fr, "everyone": everyone,
        "music_by_person": music_by_person,
        "places": prune(d["places"]),
        "core_text": people_text(hh, only=CORE),
        "household_text": people_text(hh),
        "friends_text": people_text(fr),
    }
    attrs.update(other)
    return f"{total} Facts, Last Update: {ts}", attrs

def build_music(d):
    people, arts, gens, lines = {}, set(), set(), []
    for k, v in d["music"].items():
        if not isinstance(v, dict):
            continue
        a = [str(x) for x in (v.get("artists") or [])]
        g = [str(x) for x in (v.get("genres") or [])]
        n = pname(d, k)
        people[k] = {"name": n, "genres": g, "artists": a}
        arts.update(a)
        gens.update(g)
        lines.append(f"{n.upper()}\n  genres: {', '.join(g)}\n  artists: {', '.join(a)}")
    artists = sorted(arts, key=str.lower)
    genres = sorted(gens, key=str.lower)
    return len(artists), {
        "people": people,
        "artists": artists, "artists_text": ", ".join(artists),
        "genres": genres, "genres_text": ", ".join(genres),
        "music_text": "\n\n".join(lines),
    }

BUILDERS = {"info": build_info, "music": build_music}

# ---------- MQTT (with REST fallback) ----------
client = None
mq_ready = False
mq_warned = False

def disc(key):
    s = SET[key]
    return {
        "name": s["name"],
        "unique_id": s["unique_id"],
        "default_entity_id": s["entity_id"],
        "state_topic": f"{BASE}/{key}/state",
        "json_attributes_topic": f"{BASE}/{key}/attributes",
        "availability_topic": f"{BASE}/status",
        "icon": ICONS[key],
    }

def rest_post(eid, state, attrs):
    body = json.dumps({"state": state, "attributes": attrs}, default=str).encode()
    req = urllib.request.Request(
        f"http://supervisor/core/api/states/{eid}", data=body, method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()

def publish_all():
    try:
        d = load()
        built = {k: fn(d) for k, fn in BUILDERS.items()}
    except Exception as e:
        print("Build failed:", e, flush=True)
        return
    try:
        if client is not None:
            if not mq_ready:
                return  # on_connect publishes once the broker is up
            client.publish(f"{BASE}/status", "online", qos=1, retain=True)
            for k, (state, attrs) in built.items():
                client.publish(f"homeassistant/sensor/{BASE}/{k}/config",
                               json.dumps(disc(k)), qos=1, retain=True)
                client.publish(f"{BASE}/{k}/state", str(state), qos=1, retain=True)
                client.publish(f"{BASE}/{k}/attributes",
                               json.dumps(attrs, ensure_ascii=False, default=str),
                               qos=1, retain=True)
            print("MQTT sensors published", flush=True)
        else:
            for k, (state, attrs) in built.items():
                a = dict(attrs)
                a["friendly_name"] = SET[k]["name"]
                a["icon"] = ICONS[k]
                rest_post(SET[k]["entity_id"], state, a)
            print("REST sensors published (no unique ID)", flush=True)
    except Exception as e:
        print("Publish failed:", e, flush=True)

def on_connect(c, u, flags, *a):
    global mq_ready
    mq_ready = True
    print("Connected to MQTT broker", flush=True)
    c.subscribe("homeassistant/status")
    publish_all()

def on_disconnect(c, u, *a):
    global mq_ready
    mq_ready = False
    print("Disconnected from MQTT broker", flush=True)

def on_message(c, u, msg):
    if msg.payload == b"online":  # HA just restarted
        publish_all()

def start_mqtt():
    global client, mq_warned
    if client is not None:
        return
    try:
        host = (OPT.get("mqtt_host") or "").strip()
        if host:
            c = {"host": host, "port": OPT.get("mqtt_port") or 1883,
                 "username": (OPT.get("mqtt_username") or "").strip() or None,
                 "password": OPT.get("mqtt_password") or None, "ssl": False}
            print("Using external MQTT broker at", host, flush=True)
        else:
            req = urllib.request.Request(
                "http://supervisor/services/mqtt",
                headers={"Authorization": f"Bearer {TOKEN}"})
            c = json.load(urllib.request.urlopen(req, timeout=10))["data"]
        try:
            cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            cl = mqtt.Client()
        if c.get("username"):
            cl.username_pw_set(c["username"], c.get("password"))
        if c.get("ssl"):
            cl.tls_set()
        cl.will_set(f"{BASE}/status", "offline", qos=1, retain=True)
        cl.on_connect = on_connect
        cl.on_disconnect = on_disconnect
        cl.on_message = on_message
        cl.connect_async(c["host"], int(c.get("port", 1883)), 60)
        cl.loop_start()
        client = cl
    except Exception as e:
        if not mq_warned:
            print(f"MQTT not available ({e}), using REST fallback", flush=True)
            mq_warned = True

# ---------- web ----------
async def index(r):
    return web.FileResponse("/index.html")

async def get_data(r):
    return web.json_response(load())

async def post_data(r):
    d = await r.json()
    if not isinstance(d, dict) or not all(k in d for k in KEYS):
        return web.json_response({"ok": False}, status=400)
    save(d)
    publish_all()
    return web.json_response({"ok": True})

async def get_settings(r):
    out = {k: {"name": SET[k]["name"], "entity_id": SET[k]["entity_id"],
               "unique_id": SET[k]["unique_id"]} for k in DEFAULTS}
    out["mode"] = "MQTT (has unique ID)" if client is not None else "REST (no unique ID)"
    return web.json_response(out)

async def post_settings(r):
    d = await r.json()
    for k in DEFAULTS:
        n = (d.get(k) or "").strip()
        if n:
            SET[k]["name"] = n
    save_settings(SET)
    publish_all()
    return web.json_response({"ok": True})

async def start_bg(app):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, start_mqtt)
    await loop.run_in_executor(None, publish_all)
    async def tick():
        n = 0
        while True:
            await asyncio.sleep(60)
            n += 1
            if client is None:
                await loop.run_in_executor(None, start_mqtt)
            if n % 10 == 0:
                await loop.run_in_executor(None, publish_all)
    _spawn(tick())

_BG_TASKS: set = set()  # keep references so background tasks are not garbage-collected mid-run


def _spawn(coro):
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task


app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/api/data", get_data)
app.router.add_post("/api/data", post_data)
app.router.add_get("/api/settings", get_settings)
app.router.add_post("/api/settings", post_settings)
app.on_startup.append(start_bg)
web.run_app(app, host="0.0.0.0", port=8099)
