"""Arrivals: who just arrived where, for any zone (not only home).

This is the add-on version of the old AppDaemon "PresenceSensors" app (sensor.arrived_home), widened
so it works for every zone in Home Assistant:

* People come from Location > Devices, so there is nothing to type twice.
* Each zone gets a sensor, sensor.arrived_<zone> (zone.home gives sensor.arrived_home, as before).
  Its state is who arrived: "alex_home", "alex_sam_work", or a group name you chose.
* People who arrive at the same place within `window_seconds` count as one group.
* After `reset_after_seconds` the sensor goes back to "no one arriving". When nobody is at the
  place it shows "nobody home" (home) or "nobody here" (any other place).
* sensor.latest_arrival shows the newest arrival anywhere, and every arrival fires a
  `location_hub_arrival` event for automations.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import deque
from datetime import datetime, timezone

import aiohttp
from aiohttp import web

from . import tracker

log = logging.getLogger("hub.arrivals")

DATA_DIR = os.environ.get("MT_HUB_DATA", "/data/hub")
CFG_PATH = os.path.join(DATA_DIR, "arrivals.json")
PUB_PATH = os.path.join(DATA_DIR, "arrivals_published.json")  # which sensors exist in MQTT (not part of backups)

API = tracker.API
WS = tracker.WS
HDR = tracker.H

NONE_STATE = "no one arriving"
EVENT = "location_hub_arrival"
BAD_STATES = {"", "unknown", "unavailable", "none"}
IGNORE = object()  # place_of() result for "this state says nothing, keep where they were"

DEFAULT = {
    "settings": {
        "enabled": True,
        "all_zones": True,
        "latest_sensor": True,
        "fire_events": True,
        "window_seconds": 180,
        "reset_after_seconds": 300,
    },
    "places": [],
}


def slug(text) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(text or "").lower()).strip("_")


def zslug(zone: str) -> str:
    return zone.split(".", 1)[1] if "." in zone else zone


def clean(c) -> dict:
    """Make any saved or posted config safe to use."""
    c = c if isinstance(c, dict) else {}
    src = c.get("settings") if isinstance(c.get("settings"), dict) else {}
    s = {}
    for k, d in DEFAULT["settings"].items():
        v = src.get(k, d)
        if isinstance(d, bool):
            s[k] = bool(v)
        else:
            try:
                s[k] = max(5, min(86400, int(v)))
            except (TypeError, ValueError):
                s[k] = d
    places, seen = [], set()
    for p in c.get("places") or []:
        if not isinstance(p, dict):
            continue
        zone = str(p.get("zone") or "").strip().lower()
        if not zone.startswith("zone.") or zone in seen:
            continue
        seen.add(zone)
        combos = []
        for cb in p.get("combos") or []:
            if not isinstance(cb, dict):
                continue
            name = slug(cb.get("name"))
            people = sorted({slug(x) for x in (cb.get("people") or []) if slug(x)})
            if name and people:
                combos.append({"name": name, "people": people})
        places.append({"id": str(p.get("id") or slug(zone)), "zone": zone,
                       "enabled": p.get("enabled", True) is not False, "combos": combos})
    return {"settings": s, "places": places}


def load_cfg() -> dict:
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            return clean(json.load(f))
    except (OSError, ValueError):
        return clean(DEFAULT)


def save_cfg(c: dict) -> None:
    with open(CFG_PATH, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=2)


def load_published() -> dict:
    try:
        with open(PUB_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return {"places": [str(x) for x in d.get("places", [])], "latest": bool(d.get("latest"))}
    except (OSError, ValueError, AttributeError):
        return {"places": [], "latest": False}


def save_published(d: dict) -> None:
    try:
        with open(PUB_PATH, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except OSError as e:
        log.warning("Could not save the published sensor list: %s", e)


class App:
    def __init__(self):
        self.cfg = load_cfg()
        self.http = None
        self.snap = {}        # entity_id -> state text, for every entity (cheap, lets new people start correctly)
        self.where = {}       # person id -> zone entity they are in now, or None
        self.zones = {}       # zone entity -> friendly name
        self.rt = {}          # zone entity -> {"buffer": [(person id, ts)], "state", "ts", "attrs"}
        self.latest = {"state": NONE_STATE, "attrs": {}, "ts": 0.0}
        self.events = deque(maxlen=60)
        self.published = load_published()
        self.ready = False
        self._people = ([], 0.0)
        self._tasks: set = set()
        tracker.MQ_HOOKS.append(self.publish_all_mq)  # re-publish everything whenever MQTT (re)connects

    # ---------- small helpers ----------
    def _spawn(self, coro):
        t = asyncio.ensure_future(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)
        return t

    def people(self) -> list:
        """The people from Location > Devices: id (slug of the label), label, entity, home-state override."""
        rows, at = self._people
        if time.time() - at > 5:
            rows = []
            for d in tracker.load_devices():
                label = str(d.get("label") or "").strip()
                eid = str(d.get("entity_id") or "").strip().lower()
                if label and eid and slug(label):
                    rows.append({"id": slug(label), "label": label, "entity_id": eid,
                                 "home_state": str(d.get("home_state") or "").strip().lower()})
            self._people = (rows, time.time())
        return rows

    def label(self, pid: str) -> str:
        return next((p["label"] for p in self.people() if p["id"] == pid), pid)

    def zname(self, zone: str) -> str:
        return self.zones.get(zone) or zslug(zone).replace("_", " ").title()

    def place_cfg(self, zone: str):
        return next((p for p in self.cfg["places"] if p["zone"] == zone), None)

    def tracked(self, zone: str) -> bool:
        p = self.place_cfg(zone)
        return p["enabled"] if p else self.cfg["settings"]["all_zones"]

    def wanted(self) -> dict:
        """slug -> zone entity for every zone that gets a sensor."""
        return {zslug(z): z for z in self.zones if self.tracked(z)}

    def idle_text(self, zone: str) -> str:
        return "nobody home" if zone == "zone.home" else "nobody here"

    def here(self, zone: str) -> list:
        return [pid for pid, z in self.where.items() if z == zone]

    def place_of(self, person: dict, state):
        """Which zone does this person's entity say they are in? None = away, IGNORE = unknown."""
        s = str(state if state is not None else "").strip().lower()
        if s in BAD_STATES:
            return IGNORE
        hs = person["home_state"]
        if s == "home" or (hs and s == hs):
            return "zone.home"
        if s == "not_home":
            return None
        for z, name in self.zones.items():
            if s == name.lower() or s == zslug(z):
                return z
        return None

    def runtime(self, zone: str) -> dict:
        rt = self.rt.get(zone)
        if rt is None:
            rt = self.rt[zone] = {"buffer": [], "ts": 0.0, "attrs": {},
                                  "state": NONE_STATE if self.here(zone) else self.idle_text(zone)}
            rt["attrs"] = self.attrs(zone, [], 0.0)
        return rt

    def attrs(self, zone: str, recent: list, ts: float) -> dict:
        s = zslug(zone)
        a = {"place": self.zname(zone), "zone": zone,
             "people": [self.label(p) for p in recent],
             "arrived_at": datetime.fromtimestamp(ts, timezone.utc).isoformat() if ts else None,
             "count_here": len(self.here(zone))}
        for p in self.people():
            a[f"{p['id']}_{s}"] = self.where.get(p["id"]) == zone
        return a

    def combo_key(self, zone: str, recent: list) -> str:
        pc = self.place_cfg(zone)
        for cb in (pc["combos"] if pc else []):
            if set(cb["people"]) == set(recent):
                return cb["name"]
        return "_".join(sorted(recent)) + "_" + zslug(zone)

    def note(self, place: str, kind: str, msg: str) -> None:
        self.events.appendleft({"t": datetime.now().strftime("%b %d %I:%M:%S %p"), "place": place,
                                "kind": kind, "msg": msg})

    # ---------- the arrival logic (same idea as the AppDaemon app, for any zone) ----------
    def arrived(self, zone: str, pid: str, test: bool = False) -> None:
        s = self.cfg["settings"]
        if not test and (not s["enabled"] or not self.tracked(zone)):
            return
        rt = self.runtime(zone)
        now = time.time()
        rt["buffer"].append((pid, now))
        rt["buffer"] = [(n, t) for n, t in rt["buffer"] if now - t <= s["window_seconds"]]
        recent = sorted({n for n, _ in rt["buffer"]})
        key = self.combo_key(zone, recent)
        rt["state"], rt["ts"] = key, now
        rt["attrs"] = self.attrs(zone, recent, now)
        self.latest = {"state": key, "attrs": dict(rt["attrs"], place_slug=zslug(zone)), "ts": now}
        names = ", ".join(self.label(p) for p in recent)
        log.info("%s arrived at %s -> %s%s", names, self.zname(zone), key, " (test)" if test else "")
        self.note(self.zname(zone), "test" if test else "arrival", f"{names} -> {key}")
        self.publish_place(zone)
        self.publish_latest()
        if s["fire_events"]:
            self._spawn(self._fire(zone, recent, key, test))

    def left(self, zone: str, pid: str) -> None:
        rt = self.rt.get(zone)
        if rt is None:
            return
        rt["buffer"] = [(n, t) for n, t in rt["buffer"] if n != pid]
        if not self.here(zone):
            rt["buffer"], rt["ts"], rt["state"] = [], 0.0, self.idle_text(zone)
            rt["attrs"] = self.attrs(zone, [], 0.0)
        else:
            recent = sorted({n for n, _ in rt["buffer"]})
            rt["attrs"] = self.attrs(zone, recent, rt["ts"])
        self.publish_place(zone)

    def reset_tick(self) -> None:
        now = time.time()
        after = self.cfg["settings"]["reset_after_seconds"]
        for zone, rt in list(self.rt.items()):
            if rt["state"] in (NONE_STATE, "nobody home", "nobody here"):
                continue
            if not self.here(zone):
                rt["buffer"], rt["ts"], rt["state"] = [], 0.0, self.idle_text(zone)
                rt["attrs"] = self.attrs(zone, [], 0.0)
                self.publish_place(zone)
            elif rt["ts"] and now - rt["ts"] >= after:
                rt["state"] = NONE_STATE
                self.publish_place(zone)
        if self.latest["state"] != NONE_STATE and now - self.latest["ts"] >= after:
            self.latest = {"state": NONE_STATE, "attrs": self.latest["attrs"], "ts": self.latest["ts"]}
            self.publish_latest()

    async def reset_loop(self) -> None:
        while True:
            await asyncio.sleep(30)
            try:
                if tracker.mq is None:
                    await tracker.setup_mqtt(self.http)  # rate limited inside; keeps trying MQTT
                self.reset_tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("reset check failed")

    # ---------- Home Assistant events ----------
    def on_state(self, eid: str, new) -> None:
        try:
            if eid.startswith("zone."):
                self._zone_event(eid, new)
            elif new:
                for p in self.people():
                    if p["entity_id"] == eid:
                        self._person_event(p, new.get("state"))
        except Exception:  # noqa: BLE001
            log.exception("state change for %s failed", eid)
        finally:
            if new:
                self.snap[eid] = new.get("state")
            else:
                self.snap.pop(eid, None)

    def _person_event(self, p: dict, state) -> None:
        if not self.ready:
            return
        zone = self.place_of(p, state)
        if zone is IGNORE:
            return
        pid = p["id"]
        if pid not in self.where:  # a person added after start: begin from what they were before this change
            o = self.place_of(p, self.snap.get(p["entity_id"]))
            self.where[pid] = None if o is IGNORE else o
        old = self.where[pid]
        if zone == old:
            return
        self.where[pid] = zone
        if old:
            self.left(old, pid)
        if zone:
            self.arrived(zone, pid)

    def _zone_event(self, eid: str, new) -> None:
        if new is None:
            changed = self.zones.pop(eid, None) is not None
        else:
            name = (new.get("attributes") or {}).get("friendly_name") or zslug(eid).replace("_", " ").title()
            changed = self.zones.get(eid) != name
            self.zones[eid] = name
        if changed and self.ready:
            self.publish_all()

    async def load(self) -> None:
        async with self.http.get(f"{API}/states", headers=HDR, timeout=aiohttp.ClientTimeout(total=30)) as r:
            allst = await r.json()
        self.snap = {s["entity_id"]: s["state"] for s in allst}
        self.zones = {s["entity_id"]: (s["attributes"].get("friendly_name") or zslug(s["entity_id"]).title())
                      for s in allst if s["entity_id"].startswith("zone.")}
        self.where = {}
        for p in self.people():
            z = self.place_of(p, self.snap.get(p["entity_id"]))
            self.where[p["id"]] = None if z is IGNORE else z
        if tracker.mq is None:
            await tracker.setup_mqtt(self.http)
        self.ready = True
        self.publish_all()

    async def ws_loop(self) -> None:
        while True:
            try:
                async with self.http.ws_connect(WS, heartbeat=30) as ws:
                    await ws.receive_json()
                    await ws.send_json({"type": "auth", "access_token": tracker.TOKEN})
                    m = await ws.receive_json()
                    if m.get("type") != "auth_ok":
                        raise RuntimeError(f"auth failed: {m}")
                    await self.load()
                    await ws.send_json({"id": 1, "type": "subscribe_events", "event_type": "state_changed"})
                    log.info("Arrivals connected to Home Assistant (%d zones, %d people)",
                             len(self.zones), len(self.people()))
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        d = json.loads(msg.data)
                        if d.get("type") == "event":
                            ev = d["event"]["data"]
                            self.on_state(ev["entity_id"], ev.get("new_state"))
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("Arrivals websocket dropped: %s", e)
            self.ready = False
            await asyncio.sleep(10)

    async def run(self) -> None:
        t = asyncio.ensure_future(self.reset_loop())
        try:
            await self.ws_loop()
        finally:
            t.cancel()

    async def _fire(self, zone: str, recent: list, key: str, test: bool) -> None:
        body = {"place": self.zname(zone), "zone": zone, "place_slug": zslug(zone),
                "people": [self.label(p) for p in recent], "ids": recent, "key": key, "test": test}
        try:
            async with self.http.post(f"{API}/events/{EVENT}", json=body, headers=HDR,
                                      timeout=aiohttp.ClientTimeout(total=15)) as r:
                if r.status >= 400:
                    log.warning("Could not fire %s: HTTP %s", EVENT, r.status)
        except Exception as e:  # noqa: BLE001
            log.warning("Could not fire %s: %s", EVENT, e)

    # ---------- publishing (MQTT discovery, with a plain REST fallback) ----------
    def _client(self):
        c = tracker.mq
        return c if (c is not None and tracker.mq_ready) else None

    @staticmethod
    def _place_topics(sl: str):
        base = f"{tracker.BASE_TOPIC}/arrivals/{sl}"
        return f"{base}/state", f"{base}/attributes", f"homeassistant/sensor/{tracker.UID}/arr_z_{sl}/config"

    @staticmethod
    def _latest_topics():
        base = f"{tracker.BASE_TOPIC}/arrivals/_latest"
        return f"{base}/state", f"{base}/attributes", f"homeassistant/sensor/{tracker.UID}/arr_latest/config"

    def _mq_place(self, c, zone: str) -> None:
        sl = zslug(zone)
        st, at, cfg = self._place_topics(sl)
        rt = self.runtime(zone)
        c.publish(cfg, json.dumps({
            "name": f"Arrived {self.zname(zone)}", "unique_id": f"{tracker.UID}_arr_{sl}",
            "default_entity_id": f"sensor.arrived_{sl}", "state_topic": st, "json_attributes_topic": at,
            "availability_topic": tracker.AVAIL_T, "icon": "mdi:map-marker-check"}), qos=1, retain=True)
        c.publish(at, json.dumps(rt["attrs"]), qos=1, retain=True)
        c.publish(st, rt["state"], qos=1, retain=True)

    def _mq_latest(self, c) -> None:
        st, at, cfg = self._latest_topics()
        c.publish(cfg, json.dumps({
            "name": "Latest Arrival", "unique_id": f"{tracker.UID}_arr_latest",
            "default_entity_id": "sensor.latest_arrival", "state_topic": st, "json_attributes_topic": at,
            "availability_topic": tracker.AVAIL_T, "icon": "mdi:account-arrow-right"}), qos=1, retain=True)
        c.publish(at, json.dumps(self.latest["attrs"]), qos=1, retain=True)
        c.publish(st, self.latest["state"], qos=1, retain=True)

    async def _rest(self, eid: str, name: str, state: str, attrs: dict) -> None:
        a = dict(attrs)
        a["friendly_name"] = name
        try:
            async with self.http.post(f"{API}/states/{eid}", json={"state": state, "attributes": a},
                                      headers=HDR, timeout=aiohttp.ClientTimeout(total=15)):
                pass
        except Exception as e:  # noqa: BLE001
            log.warning("Could not set %s: %s", eid, e)

    def publish_place(self, zone: str) -> None:
        if not self.tracked(zone) or zone not in self.zones:
            return
        c = self._client()
        if c:
            self._mq_place(c, zone)
        elif tracker.mq is None and self.http is not None:
            rt = self.runtime(zone)
            self._spawn(self._rest(f"sensor.arrived_{zslug(zone)}", f"Arrived {self.zname(zone)}",
                                   rt["state"], rt["attrs"]))

    def publish_latest(self) -> None:
        if not self.cfg["settings"]["latest_sensor"]:
            return
        c = self._client()
        if c:
            self._mq_latest(c)
        elif tracker.mq is None and self.http is not None:
            self._spawn(self._rest("sensor.latest_arrival", "Latest Arrival",
                                   self.latest["state"], self.latest["attrs"]))

    def _sync(self, c) -> None:
        """Publish every wanted sensor and clear the ones that should no longer exist."""
        want = self.wanted()
        for sl in [s for s in self.published["places"] if s not in want]:
            for topic in self._place_topics(sl):
                c.publish(topic, "", qos=1, retain=True)
        for sl, zone in want.items():
            self._mq_place(c, zone)
        want_latest = self.cfg["settings"]["latest_sensor"]
        if self.published["latest"] and not want_latest:
            for topic in self._latest_topics():
                c.publish(topic, "", qos=1, retain=True)
        if want_latest:
            self._mq_latest(c)
        self.published = {"places": sorted(want), "latest": want_latest}
        save_published(self.published)

    def publish_all(self) -> None:
        for zone in list(self.wanted().values()):
            self.runtime(zone)
        c = self._client()
        if c:
            self._sync(c)
        elif tracker.mq is None and self.http is not None:
            for zone in list(self.wanted().values()):
                self.publish_place(zone)
            self.publish_latest()
        # MQTT configured but not connected yet: tracker.on_mq_connect calls publish_all_mq() when it is.

    def publish_all_mq(self) -> None:
        """Called from tracker.on_mq_connect (paho's thread): MQTT only, no event-loop work."""
        c = self._client()
        if c and self.ready:
            self._sync(c)

    # ---------- web ----------
    async def h_get(self, req):
        zones = sorted(({"id": z, "name": n} for z, n in self.zones.items()), key=lambda x: x["name"].lower())
        return web.json_response({"settings": self.cfg["settings"], "places": self.cfg["places"],
                                  "people": [{"id": p["id"], "label": p["label"]} for p in self.people()],
                                  "zones": zones})

    async def h_set(self, req):
        try:
            body = await req.json()
        except ValueError:
            return web.json_response({"error": "bad request"}, status=400)
        if not isinstance(body, dict) or "settings" not in body or "places" not in body:
            return web.json_response({"error": "bad config"}, status=400)
        self.cfg = clean(body)
        try:
            save_cfg(self.cfg)
        except OSError as e:
            return web.json_response({"error": f"could not save: {e}"}, status=500)
        if self.ready:
            self.publish_all()
        return web.json_response({"ok": True})

    async def h_live(self, req):
        live = []
        for sl, zone in sorted(self.wanted().items()):
            rt = self.runtime(zone)
            live.append({"zone": zone, "name": self.zname(zone), "sensor": f"sensor.arrived_{sl}",
                         "state": rt["state"], "here": [self.label(p) for p in self.here(zone)]})
        return web.json_response({"live": live, "latest": {"state": self.latest["state"],
                                  "attrs": self.latest["attrs"]},
                                  "people": [{"id": p["id"], "label": p["label"]} for p in self.people()],
                                  "log": list(self.events), "connected": self.ready,
                                  "mqtt": bool(self._client())})

    async def h_test(self, req):
        try:
            b = await req.json()
        except ValueError:
            return web.json_response({"error": "bad request"}, status=400)
        zone = str((b or {}).get("zone") or "").lower()
        if zone not in self.zones:
            return web.json_response({"error": "Unknown zone."}, status=404)
        known = {p["id"] for p in self.people()}
        ids = [i for i in ((b or {}).get("people") or []) if i in known]
        if not ids:
            ids = [p["id"] for p in self.people()][:1]
        if not ids:
            return web.json_response({"error": "Add a person on Location > Devices first."}, status=400)
        for pid in ids:
            self.arrived(zone, pid, test=True)
        return web.json_response({"ok": True, "state": self.runtime(zone)["state"]})

    def routes(self):
        return [web.get("/api/hub/arrivals", self.h_get), web.post("/api/hub/arrivals", self.h_set),
                web.get("/api/hub/arrivals/live", self.h_live), web.post("/api/hub/arrivals/test", self.h_test)]
