import asyncio
import json
import logging
import os
import re
import time
from datetime import datetime
from urllib.parse import quote

import aiohttp
from aiohttp import web

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("findmy_reitti")

HDR = {"Authorization": "Bearer " + os.environ.get("SUPERVISOR_TOKEN", "")}
CORE = "http://supervisor/core/api"
DATA_FILE = "/data/state.json"
DEFAULT = {"reitti_url": "", "token": "", "interval": 30, "devices": []}

cfg = json.loads(json.dumps(DEFAULT))
status = {}     # device id -> last result shown in the UI
last_sent = {}  # device id -> last_updated stamp we already delivered


def slug(t):
    return re.sub(r"[^a-z0-9]+", "_", str(t).lower()).strip("_") or "x"


def load():
    global cfg
    try:
        with open(DATA_FILE) as f:
            cfg = {**DEFAULT, **json.load(f)}
    except FileNotFoundError:
        pass
    except Exception:
        log.exception("Could not read saved settings, starting fresh")


def save():
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, DATA_FILE)


def note(did, ok, msg):
    status[did] = {"ok": ok, "msg": msg, "t": int(time.time())}
    (log.info if ok else log.warning)("%s: %s", did, msg)


async def send(app, d, force=False):
    did = d["id"]
    token = d.get("token") or cfg["token"]
    base = cfg["reitti_url"].strip().rstrip("/")
    if not base or not token:
        return note(did, False, "Set the Reitti address and a token first")
    if not base.startswith("http"):
        base = "http://" + base
    try:
        async with app["ha"].get(f"{CORE}/states/{d['entity']}") as r:
            if r.status != 200:
                return note(did, False, f"Home Assistant can't find {d['entity']}")
            st = await r.json()
        a = st.get("attributes") or {}
        lat, lon = a.get("latitude"), a.get("longitude")
        if lat is None or lon is None:
            return note(did, False, f"No location yet (state: {st.get('state')})")
        stamp = st.get("last_updated")
        if not force and last_sent.get(did) == stamp:
            return
        try:
            tst = int(datetime.fromisoformat(stamp).timestamp())
        except Exception:
            tst = int(time.time())
        payload = {"_type": "location", "tid": d["tid"], "lat": lat, "lon": lon,
                   "acc": int(a.get("gps_accuracy") or 50), "tst": tst}
        url = f"{base}/api/v1/ingest/owntracks?token={quote(token, safe='')}"
        # app["out"] has NO default headers, so the HA token never goes to Reitti
        async with app["out"].post(url, json=payload) as r:
            if 200 <= r.status < 300:
                last_sent[did] = stamp
                note(did, True, f"Sent {lat:.5f}, {lon:.5f}")
            else:
                note(did, False, f"Reitti said {r.status}: {(await r.text())[:100]}")
    except Exception as e:
        note(did, False, f"{type(e).__name__}: {e}")


async def cycle(app, force=False):
    for d in list(cfg["devices"]):
        if d.get("enabled", True):
            await send(app, d, force)


async def poll_loop(app):
    while True:
        try:
            await cycle(app)
        except Exception:
            log.exception("Poll failed")
        await asyncio.sleep(max(10, int(cfg.get("interval", 30))))


async def index(request):
    return web.FileResponse("/app/index.html")


async def api_state(request):
    return web.json_response({"cfg": cfg, "status": status})


async def api_entities(request):
    out = []
    try:
        async with request.app["ha"].get(f"{CORE}/states") as r:
            for d in await r.json():
                eid = d["entity_id"]
                if eid.startswith(("device_tracker.", "person.")):
                    out.append({"id": eid, "name": d["attributes"].get("friendly_name", eid)})
    except Exception:
        log.exception("Could not list entities")
    out.sort(key=lambda x: x["id"])
    return web.json_response(out)


async def api_config(request):
    body = await request.json()
    devs, used = [], set()
    for x in body.get("devices", []):
        name = str(x.get("name", "")).strip()[:40]
        ent = str(x.get("entity", "")).strip()
        if not name or not ent:
            continue
        base = x.get("id") or slug(name)
        did, n = base, 2
        while did in used:
            did, n = f"{base}_{n}", n + 1
        used.add(did)
        tid = (re.sub(r"[^A-Za-z0-9]", "", str(x.get("tid", "")))[:4]
               or re.sub(r"[^A-Za-z0-9]", "", name)[:2].upper() or "XX")
        devs.append({"id": did, "name": name, "entity": ent, "tid": tid,
                     "token": str(x.get("token", "")).strip()[:200],
                     "enabled": bool(x.get("enabled", True))})
    for gone in set(status) - used:
        status.pop(gone, None)
    last_sent.clear()  # resend current spots after any settings change
    cfg["devices"] = devs
    cfg["reitti_url"] = str(body.get("reitti_url", "")).strip()[:200]
    cfg["token"] = str(body.get("token", "")).strip()[:200]
    try:
        cfg["interval"] = max(10, int(body.get("interval", 30)))
    except (TypeError, ValueError):
        cfg["interval"] = 30
    save()
    request.app["bg"] = asyncio.create_task(cycle(request.app))
    return web.json_response({"ok": True})


async def api_send(request):
    body = await request.json()
    did = body.get("id")
    d = next((x for x in cfg["devices"] if x["id"] == did), None)
    if d:
        await send(request.app, d, force=True)
    return web.json_response(status.get(did, {"ok": False, "msg": "Save first", "t": int(time.time())}))


async def on_startup(app):
    app["ha"] = aiohttp.ClientSession(headers=HDR)
    app["out"] = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15))
    app["poll"] = asyncio.create_task(poll_loop(app))


async def on_cleanup(app):
    await app["ha"].close()
    await app["out"].close()


def main():
    load()
    app = web.Application()
    app.router.add_get("/", index)
    app.router.add_get("/api/state", api_state)
    app.router.add_get("/api/entities", api_entities)
    app.router.add_post("/api/config", api_config)
    app.router.add_post("/api/send", api_send)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    web.run_app(app, host="0.0.0.0", port=8099)


if __name__ == "__main__":
    main()
