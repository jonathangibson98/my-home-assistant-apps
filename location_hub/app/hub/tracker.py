import asyncio, hashlib, json, os, logging, aiohttp, re, uuid, time
from urllib.parse import quote
from aiohttp import web
from math import radians, sin, cos, sqrt, atan2

try:
    import paho.mqtt.client as mqtt
except ImportError:
    mqtt = None

# The Location Hub keeps its files in /data/hub, separate from any older
# /data/settings.json. (An old stand-alone Location Hub install is migrated by hub.migrate_legacy_data.)
DATA_DIR = os.environ.get("MT_HUB_DATA", "/data/hub")
os.makedirs(DATA_DIR, exist_ok=True)
CONFIG_PATH = os.environ.get("MT_OPTIONS", "/data/options.json")
DEVICES_PATH = os.path.join(DATA_DIR, "devices.json")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
TRACKERS_PATH = os.path.join(DATA_DIR, "trackers.json")
CARD_PATH = os.path.join(DATA_DIR, "card.json")
# Home Assistant's www folder (served as /local/...). Needs the add-on's homeassistant_config mapping.
WWW_DIR = os.environ.get("MT_WWW", "/homeassistant/www")
PIC_SUBDIR = "location_hub"

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
    # No devices until you add them in the UI
    return []

def save_devices(entities):
    with open(DEVICES_PATH, "w") as f:
        json.dump(entities, f, indent=2)

opts = load_options()

# Logging is configured once, by main.py, from the add-on's log_level option.

TOKEN = os.environ.get("SUPERVISOR_TOKEN") or os.environ.get("MT_TOKEN", "")
H = {"Authorization": f"Bearer {TOKEN}"}
HA_BASE = os.environ.get("MT_HA_BASE", "http://supervisor/core").rstrip("/")
SUPERVISOR = os.environ.get("MT_SUPERVISOR", "http://supervisor").rstrip("/")
API = HA_BASE + "/api"
WS = HA_BASE.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/websocket"

# ---------------- Sensor settings (name + permanent unique ID) ----------------
def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "location_tracker"

def option_name():
    """The sensor name typed in the add-on's Configuration tab, as a display name.

    Accepts a plain name ("Household Locations") or the old entity-id style
    ("sensor.location_tracker", shown as "Location Tracker").
    """
    raw = str(opts.get("sensor_name") or "").strip()
    if raw.lower().startswith("sensor."):
        raw = raw.split(".", 1)[1].replace("_", " ").title()
    return raw

def load_settings():
    data = {}
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r") as f:
                data = json.load(f)
        except Exception:
            data = {}
    changed = False
    want = option_name()
    if not data.get("uid"):
        # Generated once and never changes, so renaming never creates a duplicate sensor
        data["uid"] = (opts.get("unique_id") or "").strip() or "location_tracker_" + uuid.uuid4().hex[:8]
        changed = True
    if not data.get("name"):
        data["name"] = want or "Location Tracker"
        data["option_name"] = want
        changed = True
    elif want and data.get("option_name") != want:
        # The Configuration tab value is new or changed. On the very first start after updating
        # from an older version there is nothing to compare with, so just remember it and keep
        # whatever name is already set. After that, a changed option renames the sensor.
        if "option_name" in data and data["name"] != want:
            logging.info(f"Sensor name changed in Configuration: {data['name']!r} -> {want!r}")
            data["name"] = want
        data["option_name"] = want
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

ENTITY_RE = re.compile(r"^sensor\.[a-z0-9_]+$")
SYNC_ENTITY_ID = opts.get("sync_entity_id", True) is not False
_sync = {"next": 0.0, "warned": "", "error": ""}

cache = {}

# ---------------- Idle detection (what is at the spot a device has been sitting at) ----------------
def _opt_int(name, default, lo, hi):
    try:
        v = int(opts.get(name, default))
    except (TypeError, ValueError):
        v = default
    return max(lo, min(hi, v))

IDLE_SECONDS = _opt_int("idle_minutes", 10, 0, 1440) * 60      # 0 turns the feature off
IDLE_RADIUS = _opt_int("idle_radius_m", 100, 25, 2000)          # staying inside this circle counts as "one spot"
IDLE_RETRY = 300                                                # seconds before retrying a failed lookup
idle = {}          # person label -> {"lat", "lon", "since", "next"}: where they have been sitting, since when
place_cache = {}   # (lat, lon) rounded -> what is there
_geo = {"last": 0.0, "lock": asyncio.Lock()}
POI_KEYS = ("amenity", "shop", "tourism", "leisure", "office", "healthcare", "craft", "historic", "man_made")

# ---------------- Entity ID (renamed through Home Assistant's entity registry) ----------------
async def _ws_call(ws, mid, payload):
    await ws.send_json({"id": mid, **payload})
    while True:
        msg = await ws.receive_json()
        if msg.get("id") == mid and msg.get("type") == "result":
            return msg

async def registry_sync(s, want=None):
    """Make Home Assistant's entity ID for the location sensor match `want`.

    Returns (ok, message). Also adopts the real entity ID when it was changed in Home Assistant itself,
    so the dashboard card and alerts keep pointing at the right sensor. Needs MQTT mode: the sensor
    must exist in the entity registry (the REST fallback sensor has no registry entry).
    """
    if mq is None or not mq_ready:
        return False, "MQTT is not connected yet"
    async with s.ws_connect(WS, max_msg_size=0) as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": TOKEN})
        if (await ws.receive_json()).get("type") != "auth_ok":
            return False, "Home Assistant refused the connection"
        r = await _ws_call(ws, 1, {"type": "config/entity_registry/list"})
        if not r.get("success"):
            return False, "Home Assistant would not list entities: " + ((r.get("error") or {}).get("message") or "no reason given")
        entries = r.get("result") or []
        mine = next((e for e in entries if e.get("unique_id") == UID and e.get("platform") == "mqtt"), None)
        if not mine:
            return False, "The sensor is not in Home Assistant's entity registry yet"
        current = mine["entity_id"]
        if current != entity_id():
            logging.info(f"Entity ID is {current} in Home Assistant, using that")
            SETTINGS["entity_id"] = current
            save_settings(SETTINGS)
        if not want or want == current:
            return True, ""
        r = await _ws_call(ws, 2, {"type": "config/entity_registry/update",
                                   "entity_id": current, "new_entity_id": want})
        if not r.get("success"):
            return False, (r.get("error") or {}).get("message") or "Home Assistant refused the rename"
    old = entity_id()
    SETTINGS["entity_id"] = want
    save_settings(SETTINGS)
    logging.info(f"Entity ID renamed: {old} -> {want}. Update dashboards and automations that used {old}.")
    mq_publish_discovery()
    return True, ""

async def registry_sync_safe(s, want=None):
    """registry_sync that never raises and remembers the last problem so the page can show it."""
    try:
        ok, msg = await registry_sync(s, want)
    except Exception as e:  # noqa: BLE001
        ok, msg = False, f"{type(e).__name__}: {e}"
    _sync["error"] = "" if ok else msg
    return ok, msg

async def maybe_sync_entity(s):
    """After a name change (Configuration tab or the page) rename the entity ID to match, once."""
    if not SYNC_ENTITY_ID or SETTINGS.get("entity_synced_name") == SETTINGS["name"] or time.time() < _sync["next"]:
        return
    want = "sensor." + slugify(SETTINGS["name"])
    ok, msg = await registry_sync_safe(s, want)
    if ok:
        SETTINGS["entity_synced_name"] = SETTINGS["name"]
        save_settings(SETTINGS)
        return
    _sync["next"] = time.time() + (60 if "not in" in msg or "not connected" in msg else 900)
    if msg != _sync["warned"]:
        _sync["warned"] = msg
        logging.warning(f"Could not rename the entity ID to {want}: {msg}. "
                        "If it says the ID is already used, delete the old unavailable entity in Settings > Entities.")

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
MQ_HOOKS = []  # other hub parts (arrivals) add a function here; it runs each time MQTT connects
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
    for hook in list(MQ_HOOKS):
        try:
            hook()
        except Exception:
            logging.exception("MQTT connect hook failed")

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
            async with s.get(SUPERVISOR + "/services/mqtt", headers=H,
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
    # Spaces in labels become underscores ("Sam Phone" -> "sam_phone").
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

async def place_name(s, lat, lon):
    """What is at these coordinates: a business or place name, else a street address. None on failure.

    Uses OpenStreetMap Nominatim at building level. Results are cached, and requests are spaced a
    second apart as Nominatim's usage policy asks.
    """
    key = (round(lat, 4), round(lon, 4))
    if key in place_cache:
        return place_cache[key]
    out = None
    try:
        async with _geo["lock"]:
            wait = 1.1 - (time.time() - _geo["last"])
            if wait > 0:
                await asyncio.sleep(wait)
            _geo["last"] = time.time()
            async with s.get("https://nominatim.openstreetmap.org/reverse",
                params={"lat": lat, "lon": lon, "format": "jsonv2", "zoom": 18, "addressdetails": 1},
                headers={"User-Agent": "HA-LocationTracker"},
                timeout=aiohttp.ClientTimeout(total=8)) as r:
                if r.status != 200:
                    raise RuntimeError(f"HTTP {r.status}")
                j = await r.json()
        a = j.get("address") or {}
        name = ""
        if j.get("category") not in ("highway", "boundary", "place") or j.get("type") in ("house", "building"):
            name = (j.get("name") or "").strip()
        if not name:
            for k in POI_KEYS:
                if a.get(k):
                    name = str(a[k]).strip()
                    break
        if not name:
            road = a.get("road") or a.get("pedestrian") or a.get("footway") or a.get("path")
            if road:
                num = a.get("house_number")
                name = f"{num} {road}" if num else road
        out = name or None
    except Exception as e:  # noqa: BLE001
        logging.error(f"Place lookup failed: {e}")
    if out:
        if len(place_cache) > 500:
            place_cache.clear()
        place_cache[key] = out
    return out

def idle_track(label, lat, lon):
    """Note where `label` is. Returns the idle spot dict; its "since" restarts when they leave the circle."""
    now = time.time()
    spot = idle.get(label)
    if spot is None or dist(lat, lon, spot["lat"], spot["lon"]) > IDLE_RADIUS:
        spot = idle[label] = {"lat": lat, "lon": lon, "since": now, "next": 0.0}
    return spot

async def resolve(s, eid, home_state, label=None):
    d = await state(s, eid)
    if not d:
        return "unknown", False
    st, at = d["state"], d["attributes"]

    # Case-insensitive on both sides: Home / HOME / home all match
    if home_state and st.strip().lower() == home_state.lower():
        idle.pop(label, None)
        return "Home", True

    lat, lon = at.get("latitude"), at.get("longitude")
    if lat is not None and lon is not None:
        if not home_state:
            z = await state(s, "zone.home")
            if z:
                za = z["attributes"]
                if dist(lat, lon, za["latitude"], za["longitude"]) <= za.get("radius", 100):
                    idle.pop(label, None)
                    return "Home", True
        if st.lower() in ("home", "not_home"):
            if IDLE_SECONDS and label:
                spot = idle_track(label, lat, lon)
                now = time.time()
                if now - spot["since"] >= IDLE_SECONDS and now >= spot["next"]:
                    place = await place_name(s, spot["lat"], spot["lon"])
                    if place:
                        if spot.get("place") != place:
                            spot["place"] = place
                            logging.info(f"{label} has been at one spot for {int((now - spot['since']) / 60)} min: {place}")
                        return place, False
                    spot["next"] = now + IDLE_RETRY
                elif spot.get("place") and now - spot["since"] >= IDLE_SECONDS:
                    return spot["place"], False
            return await city_state(s, lat, lon), False
        idle.pop(label, None)
        return st, False

    idle.pop(label, None)
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
        val, home = await resolve(s, eid, home_state, label)
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
    await maybe_sync_entity(s)

async def idle_watch(s):
    """A phone that sits still sends no updates, so nothing would trigger the lookup. Check every 30 s
    for anyone who has just passed the idle time and refresh the sensor for them."""
    while True:
        await asyncio.sleep(30)
        if not IDLE_SECONDS:
            return
        now = time.time()
        for spot in list(idle.values()):
            if now - spot["since"] >= IDLE_SECONDS and now >= spot["next"] and not spot.get("place"):
                await safe_update(s)
                break

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
CARD_SEED = {}  # e.g. {"alex": ("household", "person.alex")}
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

def clean_card(data):
    """The card settings from the web page, tidied up and ready to save."""
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
    return {
        "household_title": (data.get("household_title") or "").strip(),
        "friends_title": (data.get("friends_title") or "").strip(),
        "columns": max(1, min(8, cols)),
        "separator": bool(data.get("separator", True)),
        "rows": rows,
    }

async def handle_post_card(request):
    save_card(clean_card(await request.json()))
    logging.info("Updated dashboard card settings via Web UI")
    return web.json_response({"status": "ok"})

# ---------------- Card preview and picture picker ----------------
def merged_card(data):
    """The saved card with the page's unsaved edits laid over it, so the preview shows what you are doing."""
    base = load_card()
    edit = clean_card(data)
    by_key = {r["key"]: r for r in edit["rows"]}
    rows = []
    for r in base["rows"]:
        e = by_key.get(r["key"])
        rows.append(dict(r, **{k: e[k] for k in ("group", "entity", "picture")}) if e else r)
    return {
        "household_title": edit["household_title"] or base["household_title"],
        "friends_title": edit["friends_title"] or base["friends_title"],
        "columns": edit["columns"], "separator": edit["separator"], "rows": rows,
    }

async def handle_card_preview(request):
    """What the card would show right now: each tile's picture, place and home badge, plus the YAML."""
    s = request.app["session"]
    card = merged_card(await request.json())
    sensor = entity_id()
    attrs = {}
    try:
        st = await state(s, sensor)
        attrs = (st or {}).get("attributes") or {}
    except Exception:
        pass
    tiles = []
    for r in card["rows"]:
        pic, source = r["picture"], "chosen"
        if "{{" in pic:
            pic, source = "", "template"
        if not pic:
            ent = r["entity"]
            if ent.startswith("person."):
                try:
                    pic = ((await state(s, ent)) or {}).get("attributes", {}).get("entity_picture") or ""
                except Exception:
                    pic = ""
                source = "person" if pic else "none"
            else:
                pic, source = "/local/person/" + r["key"] + ".png", "default"
        loc = attrs.get(r["key"])
        tiles.append({"key": r["key"], "label": r["label"], "group": r["group"], "picture": pic, "source": source,
                      "secondary": "" if loc is None else str(loc), "home": loc == "Home",
                      "toggle": r["entity"].startswith("input_boolean.")})
    return web.json_response({"tiles": tiles, "yaml": build_card_yaml(card), "sensor": sensor})

IMG_MAGIC = ((b"\xff\xd8\xff", "jpg"), (b"\x89PNG\r\n\x1a\n", "png"), (b"GIF8", "gif"))

def sniff_image(data):
    """File extension from the first bytes, or "" when it is not a picture we accept."""
    for magic, ext in IMG_MAGIC:
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return ""

def list_www_images(limit=300):
    """Pictures in Home Assistant's www folder, newest first, as /local/ links."""
    out = []
    base = os.path.realpath(WWW_DIR)
    if not os.path.isdir(base):
        return out
    for root, dirs, files in os.walk(base):
        depth = os.path.relpath(root, base).count(os.sep) + (0 if root == base else 1)
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("community", "hacsfiles", "node_modules") and depth < 3]
        for f in files:
            if not f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                continue
            full = os.path.join(root, f)
            try:
                st = os.stat(full)
            except OSError:
                continue
            if st.st_size > 15 * 1024 * 1024:
                continue
            rel = os.path.relpath(full, base).replace(os.sep, "/")
            out.append((st.st_mtime, {"name": rel, "url": "/local/" + quote(rel)}))
    out.sort(key=lambda x: -x[0])
    return [o[1] for o in out[:limit]]

async def handle_card_pictures(request):
    """Everything the picture picker can offer: Home Assistant people with a picture, and images in www."""
    s = request.app["session"]
    people = []
    try:
        async with s.get(f"{API}/states", headers=H) as r:
            allst = await r.json() if r.status == 200 else []
        for st in allst:
            eid = st.get("entity_id", "")
            pic = (st.get("attributes") or {}).get("entity_picture")
            if eid.startswith("person.") and pic:
                people.append({"id": eid, "name": st["attributes"].get("friendly_name", eid), "url": pic})
    except Exception:
        pass
    people.sort(key=lambda x: x["name"].lower())
    loop = asyncio.get_running_loop()
    images = await loop.run_in_executor(None, list_www_images)
    return web.json_response({"people": people, "images": images, "www_ok": os.path.isdir(WWW_DIR)})

async def handle_card_upload(request):
    """Save a picture picked on the phone into www/location_hub and hand back its /local/ link."""
    try:
        reader = await request.multipart()
        field = await reader.next()
        while field is not None and field.name != "file":
            field = await reader.next()
        if field is None:
            return web.json_response({"error": "No picture came with the request."}, status=400)
        data = bytearray()
        while True:
            chunk = await field.read_chunk(256 * 1024)
            if not chunk:
                break
            data += chunk
            if len(data) > 8 * 1024 * 1024:
                return web.json_response({"error": "That picture is over 8 MB. Pick a smaller one."}, status=413)
    except Exception as e:
        return web.json_response({"error": "Could not read the upload: " + str(e)}, status=400)
    data = bytes(data)
    ext = sniff_image(data)
    if not ext:
        return web.json_response({"error": "Only JPG, PNG, WebP or GIF pictures work. (An iPhone HEIC photo needs to be sent as JPEG.)"}, status=400)
    key = re.sub(r"[^a-z0-9_]", "", (request.query.get("key") or "").lower())[:40] or "person"
    name = f"{key}-{hashlib.sha1(data).hexdigest()[:8]}.{ext}"
    folder = os.path.join(WWW_DIR, PIC_SUBDIR)
    fresh_www = not os.path.isdir(WWW_DIR)
    try:
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, name), "wb") as f:
            f.write(data)
    except OSError as e:
        return web.json_response({"error": "The add-on can't write to Home Assistant's www folder (" + str(e) + "). Update the add-on so it can see your config folder."}, status=500)
    logging.info("Saved card picture %s", name)
    return web.json_response({"url": "/local/" + PIC_SUBDIR + "/" + name, "restart_needed": fresh_www})

async def handle_get_settings(request):
    ha_id = ""
    if mq is not None and mq_ready:
        s = request.app["session"]
        if SYNC_ENTITY_ID and SETTINGS.get("entity_synced_name") != SETTINGS["name"]:
            _sync["next"] = 0
            await maybe_sync_entity(s)              # try the pending rename now; records the error if refused
        else:
            await registry_sync_safe(s, None)       # just check Home Assistant, and adopt its real ID
        ha_id = entity_id() if not _sync["error"] else ""
    return web.json_response({
        "name": SETTINGS["name"],
        "entity_id": entity_id(),
        "ha_entity_id_checked": bool(ha_id),
        "sync_error": _sync["error"],
        "unique_id": UID,
        "mode": "MQTT (has unique ID)" if mq is not None else "REST (no unique ID)",
    })

async def handle_post_settings(request):
    data = await request.json()
    s = request.app["session"]
    name = (data.get("name") or "").strip()
    if name and name != SETTINGS["name"]:
        SETTINGS["name"] = name
        SETTINGS.pop("entity_synced_name", None)   # let the entity ID follow the new name (if enabled)
        save_settings(SETTINGS)
        logging.info(f"Sensor renamed to: {name}")
        if mq is not None and mq_ready:
            mq_publish_discovery()  # same unique ID, so HA just updates the name
        _sync["next"] = 0
    new_id = (data.get("entity_id") or "").strip().lower()
    if new_id:
        if not ENTITY_RE.match(new_id):
            return web.json_response({"error": "Entity ID must look like sensor.household_locations"}, status=400)
        ok, msg = await registry_sync_safe(s, new_id)   # no-op when Home Assistant already has it
        if not ok:
            return web.json_response({"error": f"Could not change the entity ID: {msg}"}, status=400)
        SETTINGS["entity_synced_name"] = SETTINGS["name"]   # your chosen ID stays; no automatic change back
        save_settings(SETTINGS)
    else:
        await maybe_sync_entity(s)
    await safe_update(s)
    return web.json_response({"status": "ok"})

def add_routes(app):
    r = app.router
    r.add_get('/api/hub/devices', handle_get_devices)
    r.add_post('/api/hub/devices', handle_post_devices)
    r.add_get('/api/hub/trackers', handle_get_trackers)
    r.add_post('/api/hub/trackers', handle_post_trackers)
    r.add_get('/api/hub/card', handle_get_card)
    r.add_post('/api/hub/card', handle_post_card)
    r.add_post('/api/hub/card/preview', handle_card_preview)
    r.add_get('/api/hub/card/pictures', handle_card_pictures)
    r.add_post('/api/hub/card/upload', handle_card_upload)
    r.add_get('/api/hub/switches', handle_get_switches)
    r.add_post('/api/hub/toggle', handle_toggle)
    r.add_get('/api/hub/settings', handle_get_settings)
    r.add_post('/api/hub/settings', handle_post_settings)

_BG_TASKS: set = set()  # keep references so background tasks are not garbage-collected mid-run


def _spawn(coro):
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task


async def run_background(s):
    _spawn(backstop(s))
    _spawn(idle_watch(s))
    while True:
        try:
            await listen(s)
        except Exception as e:
            logging.error(f"Websocket error: {e}")
        logging.info("Disconnected, retrying in 10s...")
        await asyncio.sleep(10)
