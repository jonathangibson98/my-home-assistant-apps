import asyncio, json, os, logging, aiohttp
from aiohttp import web
from math import radians, sin, cos, sqrt, atan2

CONFIG_PATH = "/data/options.json"
DEVICES_PATH = "/data/devices.json"

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

SENSOR = opts.get("sensor_name", "sensor.location_tracker").strip()
if not SENSOR.startswith("sensor."):
    SENSOR = f"sensor.{SENSOR}"

cache = {}

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
        return "away", False
    return st, False

async def update(s):
    global ENT
    ENT = refresh_entities_map()
    attrs, count = {"friendly_name": "Location Tracker"}, 0
    for label, (eid, home_state) in ENT.items():
        val, home = await resolve(s, eid, home_state)
        attrs[label] = val
        count += home

    if opts.get("log_location_updates", True):
        logging.info(f"Updated {SENSOR} states: {attrs} (Home Count: {count})")
    else:
        logging.debug(f"Updated {SENSOR} state silently: {attrs}")

    await s.post(f"{API}/states/{SENSOR}", headers=H, json={"state": count, "attributes": attrs})

async def safe_update(s):
    try:
        await update(s)
    except Exception as e:
        logging.error(f"Update failed: {e}")

async def backstop(s):
    while True:
        await asyncio.sleep(1800)
        await safe_update(s)

async def listen(s):
    async with s.ws_connect(WS) as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": TOKEN})
        await ws.receive_json()
        await ws.send_json({"id": 1, "type": "subscribe_events", "event_type": "state_changed"})
        await ws.send_json({"id": 2, "type": "subscribe_events", "event_type": "homeassistant_started"})
        await safe_update(s)
        
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            d = msg.json()
            if d.get("type") != "event":
                continue
            ev = d["event"]
            watched = {eid for eid, _ in ENT.values()}
            if ev.get("event_type") == "homeassistant_started":
                await safe_update(s)
            elif ev["data"]["entity_id"] in watched:
                await safe_update(s)

HTML_PAGE = """<!DOCTYPE html>
<html>
<head>
    <title>Location Tracker Management</title>
    <style>
        body { font-family: sans-serif; background: #111b27; color: #e1e1e1; padding: 20px; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
        th, td { padding: 10px; border: 1px solid #334155; text-align: left; }
        th { background: #1e293b; }
        input[type="text"] { width: 95%; padding: 6px; background: #0f172a; color: #fff; border: 1px solid #334155; border-radius: 4px; }
        button { background: #2563eb; color: #fff; border: none; padding: 8px 16px; cursor: pointer; border-radius: 4px; }
        button.delete { background: #dc2626; }
        button:hover { opacity: 0.9; }
    </style>
</head>
<body>
    <h2>Location Tracker Devices</h2>
    <table id="device-table">
        <thead>
            <tr>
                <th>Label / Person</th>
                <th>Entity ID</th>
                <th>Home State Override (Optional)</th>
                <th>Action</th>
            </tr>
        </thead>
        <tbody id="rows"></tbody>
    </table>
    <button onclick="addRow()">+ Add Device</button>
    <button onclick="saveData()">Save Changes</button>

    <script>
        async function loadData() {
            let res = await fetch('api/devices');
            let data = await res.json();
            let tbody = document.getElementById('rows');
            tbody.innerHTML = '';
            data.forEach(item => addRow(item.label, item.entity_id, item.home_state));
        }

        function addRow(label = '', entity = '', homeState = '') {
            let tbody = document.getElementById('rows');
            let tr = document.createElement('tr');
            tr.innerHTML = `
                <td><input type="text" value="${label}" placeholder="e.g. Jon"></td>
                <td><input type="text" value="${entity}" placeholder="e.g. device_tracker.jon_phone"></td>
                <td><input type="text" value="${homeState}" placeholder="e.g. home"></td>
                <td><button class="delete" onclick="this.closest('tr').remove()">Delete</button></td>
            `;
            tbody.appendChild(tr);
        }

        async function saveData() {
            let rows = document.querySelectorAll('#rows tr');
            let entities = [];
            rows.forEach(tr => {
                let inputs = tr.querySelectorAll('input');
                if (inputs[0].value.trim() && inputs[1].value.trim()) {
                    entities.push({
                        label: inputs[0].value.trim(),
                        entity_id: inputs[1].value.trim(),
                        home_state: inputs[2].value.trim()
                    });
                }
            });
            let res = await fetch('api/devices', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ entities })
            });
            if (res.ok) {
                alert('Saved successfully!');
            } else {
                alert('Failed to save.');
            }
        }

        loadData();
    </script>
</body>
</html>
"""

async def handle_index(request):
    return web.Response(text=HTML_PAGE, content_type='text/html')

async def handle_get_devices(request):
    return web.json_response(load_devices())

async def handle_post_devices(request):
    global ENT
    data = await request.json()
    entities = data.get("entities", [])
    save_devices(entities)
    ENT = refresh_entities_map()
    logging.info("Updated device list via Web UI")
    return web.json_response({"status": "ok"})

async def start_web_server(s):
    app = web.Application()
    app.router.add_get('/', handle_index)
    app.router.add_get('/api/devices', handle_get_devices)
    app.router.add_post('/api/devices', handle_post_devices)
    
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', 8099)
    await site.start()

async def main():
    async with aiohttp.ClientSession() as s:
        await start_web_server(s)
        asyncio.create_task(backstop(s))
        while True:
            try:
                await listen(s)
            except Exception as e:
                logging.error(f"Websocket error: {e}")
            logging.info("Disconnected, retrying in 10s...")
            await asyncio.sleep(10)

asyncio.run(main())
