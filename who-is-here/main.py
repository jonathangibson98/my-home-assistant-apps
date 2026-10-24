import asyncio
import json
import logging
import os
import re
import threading

import aiohttp
from aiohttp import web
import paho.mqtt.client as mqtt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("whos_here")

TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HDR = {"Authorization": f"Bearer {TOKEN}"}
CORE = "http://supervisor/core/api"
DATA_FILE = "/data/state.json"
OPTIONS_FILE = "/data/options.json"
BASE = "whos_here"

DEFAULT = {
    "sensor_name": "Everybodys Locations",
    "interval": 30,
    "places": ["Home", "Work", "Away"],
    "people": [],
}

lock = threading.RLock()
cfg = json.loads(json.dumps(DEFAULT))
cache = {}      # entity_id -> raw state string
last_pub = {}   # what we last sent to MQTT
mqttc = None
connected = False


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_") or "x"


def load():
    global cfg
    try:
        with open(DATA_FILE) as f:
            cfg = {**DEFAULT, **json.load(f)}
    except FileNotFoundError:
        cfg = json.loads(json.dumps(DEFAULT))
    except Exception:
        log.exception("Could not read saved settings, starting fresh")
        cfg = json.loads(json.dumps(DEFAULT))


def save():
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, DATA_FILE)


def pretty(state):
    if state in (None, "", "unknown", "unavailable"):
        return "Unknown"
    if state == "home":
        return "Home"
    if state == "not_home":
        return "Away"
    return state[:1].upper() + state[1:] if state.islower() else state


def locations():
    out = {}
    for p in cfg["people"]:
        if p["mode"] == "manual":
            out[p["id"]] = p.get("location") or "Unknown"
        else:
            out[p["id"]] = pretty(cache.get(p.get("entity")))
    return out


# ---------------------------------------------------------------- MQTT

def pub(topic, payload, retain=True):
    if mqttc is None:
        return
    if not isinstance(payload, str):
        payload = json.dumps(payload)
    mqttc.publish(topic, payload, retain=retain)


def publish_discovery():
    with lock:
        pub(f"homeassistant/sensor/{BASE}/summary/config", {
            "name": cfg["sensor_name"],
            "unique_id": "whos_here_summary",
            "state_topic": f"{BASE}/summary/state",
            "json_attributes_topic": f"{BASE}/summary/attributes",
            "icon": "mdi:account-group",
        })
        for p in cfg["people"]:
            pid = p["id"]
            sensor_t = f"homeassistant/sensor/{BASE}/{pid}/config"
            select_t = f"homeassistant/select/{BASE}/{pid}/config"
            common = {
                "name": f"{p['name']} Location",
                "unique_id": f"whos_here_{pid}",
                "state_topic": f"{BASE}/{pid}/state",
                "icon": "mdi:account",
            }
            if p["mode"] == "manual":
                pub(sensor_t, "")
                pub(select_t, {**common,
                               "command_topic": f"{BASE}/{pid}/set",
                               "options": cfg["places"]})
            else:
                pub(select_t, "")
                pub(sensor_t, common)


def clear_person(pid):
    pub(f"homeassistant/sensor/{BASE}/{pid}/config", "")
    pub(f"homeassistant/select/{BASE}/{pid}/config", "")
    last_pub.pop(pid, None)


def publish_states(force=False):
    if not connected:
        return
    with lock:
        locs = locations()
        for p in cfg["people"]:
            v = locs[p["id"]]
            if force or last_pub.get(p["id"]) != v:
                pub(f"{BASE}/{p['id']}/state", v)
                last_pub[p["id"]] = v
        home = sum(1 for v in locs.values() if v == "Home")
        summ = (home, json.dumps(locs, sort_keys=True))
        if force or last_pub.get("_summary") != summ:
            pub(f"{BASE}/summary/state", str(home))
            pub(f"{BASE}/summary/attributes", locs)
            last_pub["_summary"] = summ


def set_manual(pid, value):
    with lock:
        for p in cfg["people"]:
            if p["id"] == pid and p["mode"] == "manual" and value in cfg["places"]:
                p["location"] = value
                save()
                return True
    return False


def on_connect(client, userdata, flags, rc, *args):
    global connected
    log.info("MQTT connected (%s)", rc)
    connected = True
    client.subscribe(f"{BASE}/+/set")
    publish_discovery()
    publish_states(force=True)


def on_disconnect(client, userdata, *args):
    global connected
    connected = False
    log.warning("MQTT disconnected")


def on_message(client, userdata, msg):
    try:
        pid = msg.topic.split("/")[1]
        if set_manual(pid, msg.payload.decode()):
            publish_states()
    except Exception:
        log.exception("Bad MQTT message")


def start_mqtt(host, port, user, password, ssl=False):
    global mqttc
    try:
        c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="whos_here")
    except AttributeError:
        c = mqtt.Client(client_id="whos_here")
    if user:
        c.username_pw_set(user, password or None)
    if ssl:
        c.tls_set()
        c.tls_insecure_set(True)
    c.on_connect = on_connect
    c.on_disconnect = on_disconnect
    c.on_message = on_message
    mqttc = c
    c.connect_async(host, int(port), 60)
    c.loop_start()
    log.info("MQTT client started -> %s:%s", host, port)


async def mqtt_setup(session):
    opts = {}
    try:
        with open(OPTIONS_FILE) as f:
            opts = json.load(f)
    except Exception:
        pass
    if opts.get("mqtt_host"):
        start_mqtt(opts["mqtt_host"], opts.get("mqtt_port") or 1883,
                   opts.get("mqtt_username"), opts.get("mqtt_password"))
        return
    while True:
        try:
            async with session.get("http://supervisor/services/mqtt") as r:
                d = (await r.json()).get("data") or {}
            if d.get("host"):
                start_mqtt(d["host"], d.get("port", 1883), d.get("username"),
                           d.get("password"), d.get("ssl", False))
                return
            log.warning("No MQTT service found. Install Mosquitto or fill in the broker in the add-on Configuration tab.")
        except Exception:
            log.exception("Could not look up MQTT service")
        await asyncio.sleep(30)


# ---------------------------------------------------------------- Home Assistant

async def refresh(session):
    with lock:
        ents = {p["entity"] for p in cfg["people"] if p["mode"] == "tracker" and p.get("entity")}
    for e in ents:
        try:
            async with session.get(f"{CORE}/states/{e}") as r:
                cache[e] = (await r.json())["state"] if r.status == 200 else None
        except Exception:
            cache[e] = None


async def poll_loop(app):
    while True:
        try:
            await refresh(app["session"])
            publish_states()
        except Exception:
            log.exception("Poll failed")
        await asyncio.sleep(max(10, int(cfg.get("interval", 30))))


# ---------------------------------------------------------------- Web UI + API

async def index(request):
    return web.FileResponse("/app/index.html")


async def api_state(request):
    with lock:
        return web.json_response({"cfg": cfg, "locs": locations()})


async def api_entities(request):
    out = []
    try:
        async with request.app["session"].get(f"{CORE}/states") as r:
            for d in await r.json():
                eid = d["entity_id"]
                if eid.startswith(("person.", "device_tracker.")):
                    out.append({"id": eid, "name": d["attributes"].get("friendly_name", eid)})
    except Exception:
        log.exception("Could not list entities")
    out.sort(key=lambda x: x["id"])
    return web.json_response(out)


async def api_config(request):
    body = await request.json()
    with lock:
        old_ids = {p["id"] for p in cfg["people"]}

        places = []
        for x in body.get("places", []):
            x = str(x).strip()[:30]
            if x and x not in places:
                places.append(x)
        if not places:
            places = ["Home", "Away"]

        people, used = [], set()
        for p in body.get("people", []):
            name = str(p.get("name", "")).strip()[:40]
            if not name:
                continue
            base = p.get("id") or slug(name)
            pid, n = base, 2
            while pid in used:
                pid, n = f"{base}_{n}", n + 1
            used.add(pid)
            item = {"id": pid, "name": name}
            if p.get("mode") == "tracker" and p.get("entity"):
                item.update(mode="tracker", entity=str(p["entity"]))
            else:
                loc = p.get("location")
                item.update(mode="manual", location=loc if loc in places else places[0])
            people.append(item)

        for gone in old_ids - used:
            clear_person(gone)

        cfg["people"] = people
        cfg["places"] = places
        cfg["sensor_name"] = str(body.get("sensor_name") or DEFAULT["sensor_name"]).strip()[:60]
        try:
            cfg["interval"] = max(10, int(body.get("interval", 30)))
        except (TypeError, ValueError):
            cfg["interval"] = 30
        save()

    publish_discovery()
    await refresh(request.app["session"])
    publish_states(force=True)
    return web.json_response({"ok": True})


async def api_set(request):
    body = await request.json()
    ok = set_manual(body.get("id"), body.get("location"))
    publish_states()
    return web.json_response({"ok": ok})


def card_yaml():
    with lock:
        sens = "sensor." + slug(cfg["sensor_name"])
        lines = ["type: grid", 'title: "Who\'s Here"', "columns: 4", "square: false", "cards:"]
        for p in cfg["people"]:
            pid = p["id"]
            lines += [
                "  - type: custom:mushroom-template-card",
                f"    primary: {json.dumps(p['name'])}",
                f"    secondary: \"{{{{ state_attr('{sens}','{pid}') }}}}\"",
            ]
            if p["mode"] == "tracker":
                ent = p["entity"]
                lines.append(f"    entity: {ent}")
                if ent.startswith("person."):
                    lines.append(f"    picture: \"{{{{ state_attr('{ent}','entity_picture') }}}}\"")
                else:
                    lines.append("    icon: mdi:account")
            else:
                lines += [f"    entity: select.{pid}_location", "    icon: mdi:account-circle"]
            lines += [
                f"    badge_icon: \"{{{{ 'mdi:home' if is_state_attr('{sens}','{pid}','Home') else 'mdi:home-off' }}}}\"",
                f"    badge_color: \"{{{{ 'green' if is_state_attr('{sens}','{pid}','Home') else 'red' }}}}\"",
                "    tap_action:",
                "      action: more-info",
            ]
        return "\n".join(lines) + "\n"


async def api_card(request):
    return web.Response(text=card_yaml(), content_type="text/plain")


async def on_startup(app):
    app["session"] = aiohttp.ClientSession(headers=HDR)
    app["poll"] = asyncio.create_task(poll_loop(app))
    app["mqtt"] = asyncio.create_task(mqtt_setup(app["session"]))


async def on_cleanup(app):
    await app["session"].close()


def main():
    load()
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/state", api_state)
    app.router.add_get("/api/entities", api_entities)
    app.router.add_post("/api/config", api_config)
    app.router.add_post("/api/set", api_set)
    app.router.add_get("/api/card", api_card)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    web.run_app(app, host="0.0.0.0", port=8099)


if __name__ == "__main__":
    main()
