"""Location Hub backup: save and restore everything this add-on keeps, as one JSON file.

A backup holds the hub's own files (devices, sensor trackers, dashboard card, sensor settings,
alert places and people) plus the add-on options from the Configuration tab. The MQTT password is
never written to a backup, and a restore keeps the one you have now.

Backups are written to a folder under /share (see the backup_path option), which is not deleted when
the add-on is uninstalled, so they can be restored into a fresh install.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time

import aiohttp
from aiohttp import web

log = logging.getLogger("hub.backup")

_BG_TASKS: set = set()  # keep references so background tasks are not garbage-collected mid-run


def _spawn(coro):
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task


DATA_DIR = os.environ.get("MT_HUB_DATA", "/data/hub")
OPTIONS_PATH = os.environ.get("MT_OPTIONS", "/data/options.json")
ROOT = os.environ.get("MT_BACKUP_ROOT", "/share")
VERSION = os.environ.get("MT_VERSION") or "dev"
SUPERVISOR = "http://supervisor"

DEFAULT_FOLDER = ROOT + "/location_hub_backups"
PREFIX = "location_hub_backup_"
SAFETY = "location_hub_safety_"
NAME_RE = re.compile(r"^location_hub_(backup|safety)_[A-Za-z0-9_.-]+\.json$")

# Everything the hub keeps in its data folder.
FILES = ("devices.json", "settings.json", "trackers.json", "card.json", "config.json")
# Add-on options worth carrying over. mqtt_password is left out on purpose, and so are the backup
# options themselves, so a restore never moves where backups are kept.
OPTION_KEYS = ("sensor_name", "sync_entity_id", "unique_id", "log_level", "log_location_updates",
               "idle_minutes", "idle_radius_m", "mqtt_host", "mqtt_port", "mqtt_username")


def read_options() -> dict:
    try:
        with open(OPTIONS_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def backup_folder() -> str:
    p = str(read_options().get("backup_path") or DEFAULT_FOLDER).strip()
    p = os.path.normpath(p)
    return p if p.startswith(ROOT + "/") else DEFAULT_FOLDER


def backup_keep() -> int:
    try:
        n = int(read_options().get("backup_keep") or 20)
    except (TypeError, ValueError):
        n = 20
    return max(1, min(200, n))


def collect() -> dict:
    files = {}
    for name in FILES:
        try:
            with open(os.path.join(DATA_DIR, name), encoding="utf-8") as f:
                files[name] = json.load(f)
        except FileNotFoundError:
            continue
        except (OSError, ValueError) as e:
            log.warning("Skipping %s in the backup: %s", name, e)
    o = read_options()
    return {"kind": "location_hub_backup", "format": 1, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
            "version": VERSION, "files": files, "options": {k: o[k] for k in OPTION_KEYS if k in o}}


def _count(v, key=None) -> int:
    if isinstance(v, dict) and key:
        v = v.get(key)
    return len(v) if isinstance(v, (list, dict)) else 0


def summarize(d: dict) -> dict:
    f = d.get("files") or {}
    return {"devices": _count(f.get("devices.json"), "entities"), "trackers": _count(f.get("trackers.json"), "trackers"),
            "places": _count(f.get("config.json"), "places"), "people": _count(f.get("config.json"), "people"),
            "options": len(d.get("options") or {})}


def parse(d) -> dict:
    """Check a backup and return it. Raises ValueError with a message the person can read."""
    if not isinstance(d, dict) or d.get("kind") != "location_hub_backup" or not isinstance(d.get("files"), dict):
        raise ValueError("That file is not a Location Hub backup.")
    for name, val in d["files"].items():
        if name not in FILES:
            raise ValueError("The backup holds a file this add-on does not use (%s)." % str(name)[:40])
        if not isinstance(val, (dict, list)):
            raise ValueError("The backup's %s is damaged." % name)
    if not isinstance(d.get("options", {}), dict):
        raise ValueError("The backup's options are damaged.")
    return d


def _write(path: str, obj) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def save_file(prefix: str = PREFIX) -> tuple[str, dict]:
    d = collect()
    name = "%s%s.json" % (prefix, time.strftime("%Y%m%d-%H%M%S"))
    folder = backup_folder()
    _write(os.path.join(folder, name), d)
    if prefix == PREFIX:
        old = sorted((n for n in os.listdir(folder) if n.startswith(PREFIX) and n.endswith(".json")), reverse=True)
        for n in old[backup_keep():]:
            try:
                os.remove(os.path.join(folder, n))
            except OSError:
                pass
    return name, d


def list_files() -> list[dict]:
    folder = backup_folder()
    try:
        names = [n for n in os.listdir(folder) if NAME_RE.match(n)]
    except OSError:
        return []
    out = []
    for n in sorted(names, reverse=True):
        p = os.path.join(folder, n)
        try:
            with open(p, encoding="utf-8") as f:
                d = parse(json.load(f))
            out.append({"file": n, "kind": "safety" if n.startswith(SAFETY) else "backup", "created": d.get("created", ""),
                        "version": d.get("version", ""), "size": os.path.getsize(p), "summary": summarize(d)})
        except (OSError, ValueError):
            continue
    return out


async def supervisor(session, method: str, path: str, body=None):
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        raise RuntimeError("not running as a Home Assistant add-on")
    async with session.request(method, SUPERVISOR + path, headers={"Authorization": "Bearer " + token}, json=body,
                               timeout=aiohttp.ClientTimeout(total=20)) as r:
        j = await r.json(content_type=None)
        if r.status >= 400 or (isinstance(j, dict) and j.get("result") == "error"):
            raise RuntimeError((j or {}).get("message") if isinstance(j, dict) and j.get("message") else "HTTP %s" % r.status)
        return j


async def apply_options(session, saved: dict) -> str:
    cur = read_options()
    new = dict(cur)
    for k in OPTION_KEYS:
        if k in saved:
            new[k] = saved[k]
    if new == cur:
        return "unchanged"
    try:
        await supervisor(session, "POST", "/addons/self/options", {"options": new})
        return "restored"
    except Exception as e:  # noqa: BLE001
        log.warning("Could not restore the add-on options: %s", e)
        return "failed: %s" % e


async def _restart_soon(session) -> None:
    await asyncio.sleep(1.5)
    try:
        await supervisor(session, "POST", "/addons/self/restart")
    except Exception as e:  # noqa: BLE001
        log.warning("Could not restart the add-on: %s", e)


def _err(msg: str, status: int = 400) -> web.Response:
    return web.json_response({"error": msg}, status=status)


async def handle_get(request: web.Request) -> web.Response:
    folder = backup_folder()
    return web.json_response({"path": folder, "keep": backup_keep(), "files": list_files(),
                              "current": summarize(collect()), "version": VERSION})


async def handle_save(request: web.Request) -> web.Response:
    try:
        name, d = save_file()
    except OSError as e:
        return _err("Could not write to %s: %s. Is the share folder available to this add-on?" % (backup_folder(), e), 500)
    log.info("Saved backup %s", name)
    return web.json_response({"ok": True, "file": name, "path": backup_folder(), "summary": summarize(d)})


async def handle_download(request: web.Request) -> web.Response:
    name = request.query.get("file")
    if name:
        if not NAME_RE.match(name):
            return _err("Unknown backup file.")
        try:
            with open(os.path.join(backup_folder(), name), "rb") as f:
                body = f.read()
        except OSError:
            return _err("That backup file is not there any more.", 404)
    else:
        name = "%s%s.json" % (PREFIX, time.strftime("%Y%m%d-%H%M%S"))
        body = json.dumps(collect(), indent=2, ensure_ascii=False).encode("utf-8")
    return web.Response(body=body, content_type="application/json",
                        headers={"Content-Disposition": 'attachment; filename="%s"' % name})


async def handle_restore(request: web.Request) -> web.Response:
    try:
        req = await request.json()
    except ValueError:
        return _err("Bad request.")
    if not isinstance(req, dict):
        return _err("Bad request.")
    try:
        if req.get("file"):
            name = str(req["file"])
            if not NAME_RE.match(name):
                return _err("Unknown backup file.")
            with open(os.path.join(backup_folder(), name), encoding="utf-8") as f:
                d = parse(json.load(f))
        else:
            name = "the uploaded file"
            d = parse(req.get("data"))
    except OSError:
        return _err("That backup file is not there any more.", 404)
    except ValueError as e:
        return _err(str(e) or "That backup is damaged.")

    # A safety copy of what is there now, so a restore can be undone.
    try:
        safety, _ = save_file(SAFETY)
    except OSError as e:
        return _err("Could not save a safety copy first (%s), so nothing was changed." % e, 500)
    try:
        for fname, val in d["files"].items():
            _write(os.path.join(DATA_DIR, fname), val)
    except OSError as e:
        return _err("Restore stopped part-way (%s). Your previous data is in %s." % (e, safety), 500)

    options = "skipped"
    if req.get("options", True) and d.get("options"):
        options = await apply_options(request.app["session"], d["options"])
    restarting = bool(os.environ.get("SUPERVISOR_TOKEN"))
    if restarting:
        _spawn(_restart_soon(request.app["session"]))
    log.info("Restored %s (safety copy %s)", name, safety)
    return web.json_response({"ok": True, "restored": sorted(d["files"]), "safety": safety, "options": options,
                              "restarting": restarting, "summary": summarize(d)})


def add_routes(app: web.Application) -> None:
    r = app.router
    r.add_get("/api/hub/backup", handle_get)
    r.add_post("/api/hub/backup/save", handle_save)
    r.add_get("/api/hub/backup/download", handle_download)
    r.add_post("/api/hub/backup/restore", handle_restore)
