import asyncio, datetime, json, os, re, shutil, time, urllib.request
import yaml
import paho.mqtt.client as mqtt
from aiohttp import web

DIR = "/homeassistant/ai_memory"
FILE = f"{DIR}/people.yaml"
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

# ---------- data file ----------
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

def save(d):
    os.makedirs(BAK, exist_ok=True)
    if os.path.exists(FILE):
        shutil.copy(FILE, f"{BAK}/people-{time.strftime('%Y%m%d-%H%M%S')}.yaml")
        for old in sorted(os.listdir(BAK))[:-20]:
            os.remove(f"{BAK}/{old}")
    tmp = FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write("# Edited via the Personalized Info app. Safe to hand-edit.\n")
        yaml.dump(d, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
    os.replace(tmp, FILE)

def load():
    if os.path.exists(FILE):
        try:
            d = yaml.safe_load(open(FILE)) or {}
            for k in KEYS:
                d.setdefault(k, {})
            return d
        except Exception as e:
            print("people.yaml unreadable, re-importing:", e, flush=True)
    d = import_merged()
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

def build_info(d):
    hh, fr, other = d["household"], d["friends"], d["other"]
    total = count_facts({"household": hh, "friends": fr, **other})
    now = datetime.datetime.now()
    ts = f"{now.strftime('%m/%d/%y')} - {now.strftime('%I:%M%p').lstrip('0').lower()}"
    everyone = {}
    for k, v in hh.items():
        if isinstance(v, dict):
            everyone[k] = {"group": "household", **v}
    for k, v in fr.items():
        if isinstance(v, dict):
            everyone[k] = {"group": "friends", **v}
    attrs = {
        "total_facts": total, "last_update": ts,
        "household_count": len(hh), "friends_count": len(fr),
        "sections": ["household", "friends"] + list(other.keys()),
        "household": hh, "friends": fr, "everyone": everyone,
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
    asyncio.create_task(tick())

app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/api/data", get_data)
app.router.add_post("/api/data", post_data)
app.router.add_get("/api/settings", get_settings)
app.router.add_post("/api/settings", post_settings)
app.on_startup.append(start_bg)
web.run_app(app, host="0.0.0.0", port=8099)
