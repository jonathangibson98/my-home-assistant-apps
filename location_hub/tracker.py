import asyncio, json, os, logging, aiohttp, re, uuid, time
from aiohttp import web
from math import radians, sin, cos, sqrt, atan2

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

CONFIG_PATH = "/data/options.json"
DEVICES_PATH = "/data/devices.json"
SETTINGS_PATH = "/data/settings.json"
TRACKERS_PATH = "/data/trackers.json"
CARD_PATH = "/data/card.json"

def load_options():
    try:
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    except Exception:
        return {
            "sensor_name": "sensor.location_tracker",
            "log_level": "INFO",
            "log_location_updates": True
        }

def load_devices():
    if os.path.exists(DEVICES_PATH):
        try:
            with open(DEVICES_PATH, "r") as f:
                return json.load(f)
        except Exception:
            pass
    # Default initial device if file doesn't exist yet
    return [{"label": "Jon", "entity_id": "device_tracker.jon_phone", "home_state": "home"}]

def save_devices(entities):
    with open(DEVICES_PATH, "w") as f:
        json.dump(entities, f, indent=2)

opts = load_options()

# Logging Configuration
LOG_LEVEL_MAP = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
}
log_level = LOG_LEVEL_MAP.get(opts.get("log_level", "INFO"), logging.INFO)
logging.basicConfig(level=log_level, format="%(asctime)s [%(levelname)s] %(message)s")

TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
H = {"Authorization": f"Bearer {TOKEN}"}
API = "http://supervisor/core/api"
WS = "ws://supervisor/core/websocket"

# ---------------- Sensor settings (name + permanent unique ID) ----------------
def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "location_tracker"

def load_settings():
    data = {}
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}
    changed = False
    if not data.get("uid"):
        # Generated once and never changes, so renaming never creates a duplicate sensor
        data["uid"] = (opts.get("unique_id") or "").strip() or "location_tracker_" + uuid.uuid4().hex[:8]
        changed = True
    if not data.get("name"):
        default = opts.get("sensor_name", "sensor.location_tracker").strip()
        default = default.split(".", 1)[-1]
        data["name"] = default.replace("_", " ").title()
        changed = True
    if not data.get("entity_id"):
        # Fixed when the sensor is first created. Renaming later only changes the display name.
        data["entity_id"] = "sensor." + slugify(data["name"])
        changed = True
    if changed:
        save_settings(data)
    return data

def save_settings(data):
    with open(SETTINGS_PATH, "w") as f:
        json.dump(data, f, indent=2)

SETTINGS = load_settings()

def entity_id():
    return SETTINGS["entity_id"]

cache = {}

# ---------------- Sensors -> device_tracker converters ----------------
def save_trackers(rows):
    with open(TRACKERS_PATH, "w") as f:
        json.dump(rows, f, indent=2)

def load_trackers():
    rows = []
    if os.path.exists(TRACKERS_PATH):
        try:
            with open(TRACKERS_PATH, "r") as f:
                rows = json.load(f)
        except Exception:
            rows = []
    changed = False
    for r in rows:
        if not r.get("id"):
            r["id"] = uuid.uuid4().hex[:8]
            changed = True
        if not r.get("tracker_id"):
            r["tracker_id"] = "device_tracker." + slugify(r.get("label", "tracker"))
            changed = True
    if changed:
        save_trackers(rows)
    return rows

CONV = load_trackers()
conv_last = {}  # row id -> {"state": "home" | "not_home", "attrs": {...}}

# ---------------- MQTT discovery (gives the sensor a real unique ID) ----------------
UID = SETTINGS["uid"]
BASE_TOPIC = f"locationtracker/{UID}"
STATE_T = f"{BASE_TOPIC}/state"
ATTR_T = f"{BASE_TOPIC}/attributes"
AVAIL_T = f"{BASE_TOPIC}/availability"
CONFIG_T = f"homeassistant/sensor/{UID}/config"

mq = None
mq_ready = False
mq_warned = False
mq_last_try = 0
last = {"count": 0, "attrs": {}}

def discovery_payload():
    return {
        "name": SETTINGS["name"],
        "unique_id": UID,
        "default_entity_id": entity_id(),
        "state_topic": STATE_T,
        "json_attributes_topic": ATTR_T,
        "availability_topic": AVAIL_T,
        "icon": "mdi:map-marker-multiple",
    }

def mq_publish_discovery():
    mq.publish(CONFIG_T, json.dumps(discovery_payload()), qos=1, retain=True)
    mq.publish(AVAIL_T, "online", qos=1, retain=True)

def mq_publish_state():
    mq.publish(STATE_T, str(last["count"]), qos=1, retain=True)
    mq.publish(ATTR_T, json.dumps(last["attrs"]), qos=1, retain=True)

# ---- device_tracker entities over MQTT ----
def conv_topics(row):
    base = f"{BASE_TOPIC}/tracker/{row['id']}"
    return f"{base}/state", f"{base}/attributes", f"homeassistant/device_tracker/{UID}/{row['id']}/config"

def conv_discovery(row):
    st, at, _ = conv_topics(row)
    return {
        "name": row["label"],
        "unique_id": f"{UID}_trk_{row['id']}",
        "default_entity_id": row["tracker_id"],
        "state_topic": st,
        "json_attributes_topic": at,
        "availability_topic": AVAIL_T,
        "payload_home": "home",
        "payload_not_home": "not_home",
        "source_type": "gps",
        "icon": "mdi:account",
    }

def conv_publish_row(row):
    st, at, cfg = conv_topics(row)
    mq.publish(cfg, json.dumps(conv_discovery(row)), qos=1, retain=True)
    lastrow = conv_last.get(row["id"])
    if lastrow:
        mq.publish(at, json.dumps(lastrow["attrs"]), qos=1, retain=True)
        mq.publish(st, lastrow["state"], qos=1, retain=True)

def conv_publish_all():
    for row in list(CONV):
        conv_publish_row(row)

def on_mq_connect(client, userdata, flags, reason_code, properties=None):
    global mq_ready
    mq_ready = True
    logging.info("Connected to MQTT broker, publishing discovery")
    mq_publish_discovery()
    mq_publish_state()
    conv_publish_all()

def on_mq_disconnect(client, userdata, *args, **kwargs):
    global mq_ready
    mq_ready = False
    logging.warning("Disconnected from MQTT broker")

async def setup_mqtt(s):
    global mq, mq_warned, mq_last_try
    if time.time() - mq_last_try < 60:
        return
    mq_last_try = time.time()

    if mqtt is None:
        if not mq_warned:
            logging.warning("paho-mqtt not installed, falling back to REST sensor (no unique ID)")
            mq_warned = True
        return
    try:
        manual_host = (opts.get("mqtt_host") or "").strip()
        if manual_host:
            # External broker (another Pi, another subnet, etc.)
            creds = {
                "host": manual_host,
                "port": opts.get("mqtt_port") or 1883,
                "username": (opts.get("mqtt_username") or "").strip() or None,
                "password": opts.get("mqtt_password") or None,
                "ssl": False,
            }
            logging.info(f"Using external MQTT broker at {manual_host}")
        else:
            # Mosquitto add-on on this same HA machine
            async with s.get("http://supervisor/services/mqtt", headers=H,
                             timeout=aiohttp.ClientTimeout(total=5)) as r:
                if r.status != 200:
                    raise RuntimeError(f"Supervisor returned {r.status}")
                creds = (await r.json()).get("data") or {}
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if creds.get("username"):
            client.username_pw_set(creds.get("username"), creds.get("password"))
        if creds.get("ssl"):
            client.tls_set()
        client.will_set(AVAIL_T, "offline", qos=1, retain=True)
        client.on_connect = on_mq_connect
        client.on_disconnect = on_mq_disconnect
        client.connect_async(creds["host"], int(creds.get("port", 1883)), 60)
        client.loop_start()
        mq = client
        logging.info("MQTT client started")
    except Exception as e:
        if not mq_warned:
            logging.warning(f"MQTT not available ({e}), falling back to REST sensor (no unique ID)")
            mq_warned = True

async def publish(s, count, attrs):
    global last
    last = {"count": count, "attrs": attrs}
    if mq is None:
        await setup_mqtt(s)
    if mq is not None:
        if mq_ready:
            mq_publish_state()
        return  # on_connect publishes everything once the broker is up
    # REST fallback: works, but HA can't give this sensor a unique ID
    rest_attrs = dict(attrs)
    rest_attrs["friendly_name"] = SETTINGS["name"]
    await s.post(f"{API}/states/{entity_id()}", headers=H,
                 json={"state": count, "attributes": rest_attrs})

def refresh_entities_map():
    # Labels, entity IDs, and home-state overrides are all forced to lowercase.
    # Spaces in labels become underscores ("MJ Phone" -> "mj_phone").
    entities = load_devices()
    return {
        e["label"].strip().lower().replace(" ", "_"): (
            e["entity_id"].strip().lower(),
            (e.get("home_state") or "").strip().lower(),
        )
        for e in entities
    }

ENT = refresh_entities_map()

def dist(a, b, c, d):
    p, q = radians(c - a), radians(d - b)
    x = sin(p/2)**2 + cos(radians(a))*cos(radians(c))*sin(q/2)**2
    return 6371000 * 2 * atan2(sqrt(x), sqrt(1 - x))

async def state(s, eid):
    async with s.get(f"{API}/states/{eid}", headers=H) as r:
        return await r.json() if r.status == 200 else None

async def city_state(s, lat, lon):
    key = (round(lat, 3), round(lon, 3))
    if key in cache:
        return cache[key]
    out = "unknown location"
    try:
        async with s.get("https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json", "zoom": 14},
            headers={"User-Agent": "HA-LocationTracker"},
            timeout=aiohttp.ClientTimeout(total=5)) as r:
            a = (await r.json()).get("address", {})
        city = a.get("city") or a.get("town") or a.get("village") or a.get("hamlet")
        st = a.get("state")
        out = f"{city}, {st}" if city and st else (st or out)
    except Exception as e:
        logging.error(f"Nominatim failed: {e}")
    cache[key] = out
    return out

async def resolve(s, eid, home_state):
    d = await state(s, eid)
    if not d:
        return "unknown", False
    st, at = d["state"], d["attributes"]

    # Case-insensitive on both sides: Home / HOME / home all match
    if home_state and st.strip().lower() == home_state.lower():
        return "Home", True

    lat, lon = at.get("latitude"), at.get("longitude")
    if lat is not None and lon is not None:
        if not home_state:
            z = await state(s, "zone.home")
            if z:
                za = z["attributes"]
                if dist(lat, lon, za["latitude"], za["longitude"]) <= za.get("radius", 100):
                    return "Home", True
        if st.lower() in ("home", "not_home"):
            return await city_state(s, lat, lon), False
        return st, False

    if not home_state and st.lower() == "home":
        return "Home", True
    if st.lower() == "not_home":
        return "Away", False
    return st, False

async def update(s):
    global ENT
    ENT = refresh_entities_map()
    attrs, count = {}, 0
    for label, (eid, home_state) in ENT.items():
        val, home = await resolve(s, eid, home_state)
        attrs[label] = val
        count += home

    if opts.get("log_location_updates", True):
        logging.info(f"Updated {entity_id()} states: {attrs} (Home Count: {count})")
    else:
        logging.debug(f"Updated {entity_id()} state silently: {attrs}")

    await publish(s, count, attrs)

# ---------------- Sensors -> device_tracker conversion ----------------
async def convert_one(s, row):
    """Home = your house coordinates. Anything else = away (not_home).
    Returns None when the source is unavailable, so a restart never flips someone to away."""
    src = (row.get("entity_id") or "").strip().lower()
    d = await state(s, src)
    if not d:
        return None
    raw = str(d.get("state", "")).strip()
    if raw.lower() in ("", "unknown", "unavailable"):
        return None

    homes = [x.strip().lower() for x in (row.get("home_state") or "home").split(",") if x.strip()]
    attrs = {"source_sensor": src, "reported_state": raw}

    if raw.lower() in homes:
        z = await state(s, "zone.home")
        if z:
            za = z["attributes"]
            attrs["latitude"] = za["latitude"]
            attrs["longitude"] = za["longitude"]
            attrs["gps_accuracy"] = 0
        return {"state": "home", "attrs": attrs}

    # Away: explicitly blank the coordinates so no old "home" position can linger on the map
    attrs["latitude"] = None
    attrs["longitude"] = None
    attrs["gps_accuracy"] = 0
    return {"state": "not_home", "attrs": attrs}

async def publish_tracker_rest(s, row, lastrow):
    attrs = dict(lastrow["attrs"])
    attrs["friendly_name"] = row["label"]
    attrs["source_type"] = "gps"
    await s.post(f"{API}/states/{row['tracker_id']}", headers=H,
                 json={"state": lastrow["state"], "attributes": attrs})

async def update_trackers(s):
    global CONV
    CONV = load_trackers()
    for row in CONV:
        try:
            res = await convert_one(s, row)
        except Exception as e:
            logging.error(f"Tracker '{row.get('label')}' failed: {e}")
            continue
        if res is None:
            continue
        conv_last[row["id"]] = res
        logging.info(f"{row['tracker_id']} -> {res['state']} (source: {row['entity_id']})")
        if mq is None:
            await publish_tracker_rest(s, row, res)
    if mq is not None and mq_ready:
        conv_publish_all()

async def remove_tracker(s, row):
    conv_last.pop(row["id"], None)
    st, at, cfg = conv_topics(row)
    if mq is not None:
        for t in (cfg, st, at):
            mq.publish(t, "", qos=1, retain=True)  # empty retained payload deletes the entity
    else:
        try:
            await s.delete(f"{API}/states/{row['tracker_id']}", headers=H)
        except Exception as e:
            logging.error(f"Could not remove {row['tracker_id']}: {e}")

async def safe_update(s):
    try:
        await update(s)
    except Exception as e:
        logging.error(f"Update failed: {e}")

async def safe_update_trackers(s):
    try:
        await update_trackers(s)
    except Exception as e:
        logging.error(f"Tracker update failed: {e}")

async def safe_update_all(s):
    await safe_update(s)
    await safe_update_trackers(s)

async def backstop(s):
    while True:
        await asyncio.sleep(1800)
        await safe_update_all(s)

async def listen(s):
    async with s.ws_connect(WS) as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": TOKEN})
        await ws.receive_json()
        await ws.send_json({"id": 1, "type": "subscribe_events", "event_type": "state_changed"})
        await ws.send_json({"id": 2, "type": "subscribe_events", "event_type": "homeassistant_started"})
        await safe_update_all(s)

        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            d = msg.json()
            if d.get("type") != "event":
                continue
            ev = d["event"]
            if ev.get("event_type") == "homeassistant_started":
                await safe_update_all(s)
                continue
            eid = ev["data"].get("entity_id")
            watched = {e for e, _ in ENT.values()}
            sources = {(r.get("entity_id") or "").strip().lower() for r in CONV}
            if eid in watched:
                await safe_update(s)
            if eid in sources:
                await safe_update_trackers(s)

# ---------------- Dashboard card generator ----------------
CARD_SEED = {
    "jon": ("household", "person.jon"),
    "mj": ("household", "person.mj"),
    "nova": ("household", "input_boolean.nova_here"),
    "blake": ("household", "input_boolean.blake_here"),
    "von": ("friends", "input_boolean.von_here"),
    "justin": ("friends", "person.justin"),
    "alli": ("friends", "input_boolean.alli_here"),
    "tyler": ("friends", "input_boolean.tyler_here"),
    "mikala": ("friends", "person.mikala"),
    "noah": ("friends", "person.noah"),
    "aaron": ("friends", "person.aaron"),
    "derek": ("friends", "input_boolean.d_here"),
    "steph": ("friends", "input_boolean.steph_here"),
}
CARD_GROUPS = ("household", "friends", "hidden")

def card_key(label):
    return label.strip().lower().replace(" ", "_")

def load_card():
    data = {}
    if os.path.exists(CARD_PATH):
        try:
            with open(CARD_PATH, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}
    saved = data.get("rows", {})
    rows = []
    for d in load_devices():
        label = (d.get("label") or "").strip()
        if not label:
            continue
        key = card_key(label)
        r = saved.get(key)
        if r is None:
            grp, ent = CARD_SEED.get(key, ("friends", "person." + key))
            r = {"group": grp, "entity": ent, "picture": ""}
        grp = r.get("group", "friends")
        rows.append({
            "key": key,
            "label": label,
            "group": grp if grp in CARD_GROUPS else "friends",
            "entity": (r.get("entity") or "").strip(),
            "picture": (r.get("picture") or "").strip(),
        })
    try:
        cols = int(data.get("columns", 4))
    except Exception:
        cols = 4
    return {
        "household_title": data.get("household_title") or "Household Locations",
        "friends_title": data.get("friends_title") or "Friends Locations",
        "columns": max(1, min(8, cols)),
        "separator": bool(data.get("separator", True)),
        "rows": rows,
    }

def save_card(card):
    out = {
        "household_title": card.get("household_title", ""),
        "friends_title": card.get("friends_title", ""),
        "columns": card.get("columns", 4),
        "separator": bool(card.get("separator", True)),
        "rows": {r["key"]: {"group": r["group"], "entity": r["entity"], "picture": r["picture"]}
                 for r in card.get("rows", [])},
    }
    with open(CARD_PATH, "w") as f:
        json.dump(out, f, indent=2)

def _yq(s):
    # YAML single-quoted string: a single quote is written as two
    return "'" + str(s).replace("'", "''") + "'"

def card_tile(row, sensor):
    key, ent = row["key"], row["entity"]
    toggle = ent.startswith("input_boolean.")
    sec = "{{ state_attr('" + sensor + "','" + key + "') }}"
    home_if = "is_state_attr('" + sensor + "','" + key + "','Home')"
    if row["picture"]:
        pic = _yq(row["picture"])
    elif ent.startswith("person."):
        pic = _yq("{{ state_attr('" + ent + "','entity_picture') }}")
    else:
        pic = "/local/person/" + key + ".png"
    lines = [
        "- type: custom:mushroom-template-card",
        "  primary: " + _yq(row["label"]),
        "  secondary: " + _yq(sec),
    ]
    if ent:
        lines.append("  entity: " + ent)
    lines += [
        "  picture: " + pic,
        "  badge_icon: >-",
        "    {{ 'mdi:home' if " + home_if + " else 'mdi:home-off' }}",
        "  badge_color: >-",
        "    {{ 'green' if " + home_if + " else 'red' }}",
    ]
    if toggle:
        lines += ["  tap_action:", "    action: toggle",
                  "  icon_tap_action:", "    action: toggle"]
    else:
        lines += ["  tap_action:", "    action: none",
                  "  hold_action:", "    action: none",
                  "  double_tap_action:", "    action: none"]
    return lines

def build_card_yaml(card=None):
    card = card or load_card()
    sensor = entity_id()

    def grid(title, rows):
        out = ["- type: grid", "  title: " + _yq(title), "  columns: " + str(card["columns"]),
               "  square: false", "  cards:"]
        for r in rows:
            out += ["    " + ln for ln in card_tile(r, sensor)]
        return out

    grids = []
    for grp, title in (("household", card["household_title"]), ("friends", card["friends_title"])):
        rows = [r for r in card["rows"] if r["group"] == grp]
        if rows:
            grids += ["      " + ln for ln in grid(title, rows)]
    if not grids:
        return "# No people in the card yet. Add devices above and save."

    out = ["type: vertical-stack", "cards:"]
    if card["separator"]:
        out += ["  - type: custom:bubble-card", "    card_type: separator",
                "    sub_button:", "      main: []", "      bottom: []"]
    out += ["  - type: vertical-stack", "    cards:"] + grids
    return "\n".join(out) + "\n"

# ---------------- Clickable switches ----------------
TOGGLE_DOMAINS = ("input_boolean", "switch")

def switch_list():
    """Entities the Switches section may show and toggle: dashboard card people whose tap
    entity is an input_boolean/switch, plus device tracker rows with Toggle ticked."""
    items, seen = [], set()

    def add(label, eid):
        eid = (eid or "").strip().lower()
        if eid.split(".")[0] not in TOGGLE_DOMAINS or eid in seen:
            return
        seen.add(eid)
        items.append({"label": label, "entity_id": eid})

    for r in load_card()["rows"]:
        if r["group"] != "hidden":
            add(r["label"], r["entity"])
    for r in load_trackers():
        if r.get("toggle"):
            add(r.get("label", ""), r.get("entity_id"))
    return items

async def handle_get_switches(request):
    s = request.app["session"]
    out = []
    for it in switch_list():
        d = await state(s, it["entity_id"])
        out.append({**it, "state": d["state"] if d else "unavailable"})
    return web.json_response(out)

async def handle_toggle(request):
    s = request.app["session"]
    data = await request.json()
    eid = (data.get("entity_id") or "").strip().lower()
    if eid not in {i["entity_id"] for i in switch_list()}:
        return web.json_response({"status": "not allowed"}, status=403)
    domain = eid.split(".")[0]
    async with s.post(f"{API}/services/{domain}/toggle", headers=H, json={"entity_id": eid}) as r:
        if r.status >= 400:
            logging.error(f"Toggle {eid} failed: HTTP {r.status}")
            return web.json_response({"status": "failed"}, status=502)
    logging.info(f"Toggled {eid} from Web UI")
    return web.json_response({"status": "ok"})

async def handle_get_devices(request):
    return web.json_response(load_devices())

async def handle_post_devices(request):
    global ENT
    data = await request.json()
    entities = data.get("entities", [])
    save_devices(entities)
    ENT = refresh_entities_map()
    logging.info("Updated device list via Web UI")
    await safe_update_all(request.app["session"])
    return web.json_response({"status": "ok"})

async def handle_get_trackers(request):
    return web.json_response(load_trackers())

async def handle_post_trackers(request):
    global CONV
    data = await request.json()
    incoming = data.get("trackers", [])
    old = {r["id"]: r for r in load_trackers()}
    old_tids = {r["tracker_id"] for r in old.values()}

    new, used = [], set()
    for r in incoming:
        label = (r.get("label") or "").strip()
        src = (r.get("entity_id") or "").strip()
        if not label or not src:
            continue
        rid = r.get("id") if r.get("id") in old else uuid.uuid4().hex[:8]
        if rid in old:
            tid = old[rid]["tracker_id"]  # fixed at creation, renaming never moves it
        else:
            base = "device_tracker." + slugify(label)
            tid, n = base, 2
            while tid in used or tid in old_tids:
                tid = f"{base}_{n}"
                n += 1
        used.add(tid)
        new.append({
            "id": rid,
            "label": label,
            "entity_id": src,
            "home_state": (r.get("home_state") or "").strip(),
            "toggle": bool(r.get("toggle")),
            "tracker_id": tid,
        })

    kept = {r["id"] for r in new}
    removed = [r for i, r in old.items() if i not in kept]
    save_trackers(new)
    CONV = new
    for r in removed:
        await remove_tracker(request.app["session"], r)
    logging.info(f"Updated sensor-to-tracker list via Web UI ({len(new)} active, {len(removed)} removed)")
    await safe_update_trackers(request.app["session"])
    return web.json_response({"status": "ok"})

async def handle_get_card(request):
    card = load_card()
    card["yaml"] = build_card_yaml(card)
    return web.json_response(card)

async def handle_post_card(request):
    data = await request.json()
    rows = []
    for r in data.get("rows", []):
        key = (r.get("key") or "").strip()
        if not key:
            continue
        grp = r.get("group")
        rows.append({
            "key": key,
            "group": grp if grp in CARD_GROUPS else "friends",
            "entity": (r.get("entity") or "").strip(),
            "picture": (r.get("picture") or "").strip(),
        })
    try:
        cols = int(data.get("columns", 4))
    except Exception:
        cols = 4
    save_card({
        "household_title": (data.get("household_title") or "").strip(),
        "friends_title": (data.get("friends_title") or "").strip(),
        "columns": max(1, min(8, cols)),
        "separator": bool(data.get("separator", True)),
        "rows": rows,
    })
    logging.info("Updated dashboard card settings via Web UI")
    return web.json_response({"status": "ok"})

async def handle_get_settings(request):
    return web.json_response({
        "name": SETTINGS["name"],
        "entity_id": entity_id(),
        "unique_id": UID,
        "mode": "MQTT (has unique ID)" if mq is not None else "REST (no unique ID)",
    })

async def handle_post_settings(request):
    data = await request.json()
    name = (data.get("name") or "").strip()
    if name and name != SETTINGS["name"]:
        SETTINGS["name"] = name
        save_settings(SETTINGS)
        logging.info(f"Sensor renamed to: {name}")
        if mq is not None and mq_ready:
            mq_publish_discovery()  # same unique ID, so HA just updates the name
    await safe_update(request.app["session"])
    return web.json_response({"status": "ok"})

def add_routes(app):
    app.router.add_get('/api/devices', handle_get_devices)
    app.router.add_post('/api/devices', handle_post_devices)
    app.router.add_get('/api/trackers', handle_get_trackers)
    app.router.add_post('/api/trackers', handle_post_trackers)
    app.router.add_get('/api/card', handle_get_card)
    app.router.add_post('/api/card', handle_post_card)
    app.router.add_get('/api/switches', handle_get_switches)
    app.router.add_post('/api/toggle', handle_toggle)
    app.router.add_get('/api/settings', handle_get_settings)
    app.router.add_post('/api/settings', handle_post_settings)

async def run_background(s):
    asyncio.create_task(backstop(s))
    while True:
        try:
            await listen(s)
        except Exception as e:
            logging.error(f"Websocket error: {e}")
        logging.info("Disconnected, retrying in 10s...")
        await asyncio.sleep(10)
