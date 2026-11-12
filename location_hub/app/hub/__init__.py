"""Location Hub: who is home, switches, device trackers, dashboard card and AI arrival alerts.

This package is the second half of the add-on. It runs inside the same process and the same
ingress web server as the home page (see main.py), under /hub and /api/hub/*.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil

from aiohttp import web

log = logging.getLogger("hub")

HERE = os.path.dirname(os.path.abspath(__file__))
PAGE = os.path.join(HERE, "hub.html")
HOME = os.path.join(HERE, "home.html")

# Files an old stand-alone Location Hub (or Location Tracker / Arrival Alerts) kept in /data.
LEGACY_FILES = ("devices.json", "trackers.json", "card.json", "config.json")


def migrate_legacy_data(data_dir: str | None = None, hub_dir: str | None = None) -> list[str]:
    """Move an old stand-alone Location Hub's files from /data into /data/hub.

    Runs once: it does
    nothing when /data/hub already exists. Returns the names that were moved.
    """
    data_dir = data_dir or os.environ.get("MT_DATA", "/data")
    hub_dir = hub_dir or os.environ.get("MT_HUB_DATA", os.path.join(data_dir, "hub"))
    if os.path.isdir(hub_dir):
        return []
    moved: list[str] = []
    names = list(LEGACY_FILES)
    sp = os.path.join(data_dir, "settings.json")
    try:
        with open(sp, encoding="utf-8") as fp:
            old = json.load(fp)
        # The hub's sensor settings have uid/name/entity_id; the old map's had a "devices" section.
        if isinstance(old, dict) and "uid" in old and "devices" not in old:
            names.append("settings.json")
    except (OSError, ValueError):
        pass
    found = [n for n in names if os.path.isfile(os.path.join(data_dir, n))]
    if not found:
        return []
    os.makedirs(hub_dir, exist_ok=True)
    for n in found:
        shutil.move(os.path.join(data_dir, n), os.path.join(hub_dir, n))
        moved.append(n)
    log.info("Moved existing Location Hub data into %s: %s", hub_dir, ", ".join(moved))
    return moved


async def _forever(name: str, fn) -> None:
    """Keep a background job alive: one failing never takes the others  down."""
    while True:
        try:
            await fn()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("%s crashed, restarting in 10s", name)
        await asyncio.sleep(10)


async def page(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(PAGE, headers={"Cache-Control": "no-store"})


async def home(request: web.Request) -> web.StreamResponse:
    return web.FileResponse(HOME, headers={"Cache-Control": "no-store"})


def setup(app: web.Application, session):
    """Register the hub's pages and API on the admin app. Returns the background jobs to run.

    Call before the app is started (routes cannot be added afterwards). `session` is a shared
    aiohttp.ClientSession for Home Assistant, MQTT discovery lookups and reverse geocoding.
    """
    migrate_legacy_data()
    from . import alerts, backup, tracker  # imported late: they read their data files at import time

    app["session"] = session
    alerts_app = alerts.App(tracker.entity_id)
    alerts_app.http = session
    app["hub_alerts"] = alerts_app
    tracker.add_routes(app)
    backup.add_routes(app)
    app.router.add_get("/", home)
    app.router.add_get("/hub", page)
    app.router.add_get("/hub/", page)
    app.router.add_routes(alerts_app.routes())

    return [
        asyncio.create_task(_forever("tracker", lambda: tracker.run_background(session)), name="hub-tracker"),
        asyncio.create_task(_forever("alerts", alerts_app.ws_loop), name="hub-alerts"),
    ]
