import asyncio, json, os, time, logging, copy
from collections import deque
from datetime import datetime
from zoneinfo import ZoneInfo
import aiohttp
from aiohttp import web

TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
API = "http://supervisor/core/api"
WS = "ws://supervisor/core/websocket"
HDR = {"Authorization": f"Bearer {TOKEN}"}
CFG_PATH = "/data/config.json"
INDEX = "/app/www/index.html"
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("arrival")

DEFAULT_STYLE = ("Generate a short rated-R arrival announcement. It should sound like a hype man "
                 "losing his mind that they finally showed up. Slightly rude, sarcastic, and funny. Can be crude.")

def place(pid, name, zone, who, mode="any", dwell=5, title="", extra="", days=None, start="", end=""):
    return {"id": pid, "enabled": True, "name": name, "zone": zone, "who": who, "mode": mode,
            "dwell": dwell, "title": title, "extra": extra, "days": days or [], "start": start,
            "end": end, "custom_prompt": ""}

DEFAULT = {
    "settings": {
        "enabled": True, "ai_entity": "ai_task.gemini_pro_ai_task", "notify_service": "notify.household",
        "timezone": "America/New_York", "max_chars": 256, "cooldown_min": 10, "style": DEFAULT_STYLE,
        "fallback": "{who} just pulled up to {place}!", "context_entity": "sensor.combined_info",
        "context_attribute": "content", "locations_entity": "sensor.household_locations",
    },
    "people": [
        {"id": "jon", "name": "Jon", "entity_id": "person.jon", "notes": ""},
        {"id": "mj", "name": "MJ", "entity_id": "person.mj", "notes": ""},
        {"id": "aaron", "name": "Aaron", "entity_id": "person.aaron", "notes": ""},
        {"id": "mikala", "name": "Mikala", "entity_id": "person.mikala", "notes": ""},
        {"id": "noah", "name": "Noah", "entity_id": "person.noah", "notes": ""},
    ],
    "places": [
        place("beer_belly_us", "Beer Belly's (Jon + MJ)", "zone.beer_bellys", ["jon", "mj"], "all", 60,
              "Beer Bellys!!", "Include our friends Aaron and Tyler. Beer Belly's is our favorite bar in Anderson, SC."),
        place("beer_belly_aaron", "Beer Belly's (Aaron)", "zone.beer_bellys", ["aaron"], "any", 10,
              "Beer Bellys!!", "Beer Belly's is Aaron's favorite bar in Anderson, SC."),
        place("mj_parents", "MJ's Parents' House", "zone.mjs_parents", [], "any", 5, "Welcome to the House!!"),
        place("mikala_house", "Mikala's House", "zone.mikalas_house", ["mikala"], "any", 3, "Mikala made it Home!!"),
        place("our_house", "Our House", "zone.home", ["noah"], "any", 0, "Welcome Noah to Our House!!"),
        place("alli_house", "Alli's House", "zone.allis_house", [], "any", 5, "Welcome to Alli's House!!",
              "Alli's house is in Anderson, SC."),
        place("work_morning", "Jon's Work (morning)", "zone.work", ["jon", "mj"], "all", 5,
              "You finally made it to work!!", "They are arriving at Jon's work in the morning.",
              [0, 1, 2, 3, 4], "07:30", "09:30"),
        place("work_afternoon", "Jon's Work (MJ, afternoon)", "zone.work", ["mj"], "any", 5, "MJ is here!!",
              "MJ is arriving at Jon's work in Anderson, SC.", [0, 1, 2, 3, 4], "12:30", "17:30"),
    ],
}

def load_cfg():
    try:
        with open(CFG_PATH) as f:
            c = json.load(f)
        for k in DEFAULT["settings"]:
            c.setdefault("settings", {}).setdefault(k, DEFAULT["settings"][k])
        c.setdefault("people", []); c.setdefault("places", [])
        return c
    except Exception:
        return copy.deepcopy(DEFAULT)

def save_cfg(c):
    with open(CFG_PATH, "w") as f:
        json.dump(c, f, indent=2)

def fmt(t, who, plc):
    return (t or "").replace("{who}", who).replace("{place}", plc)

class App:
    def __init__(self):
        self.cfg = load_cfg()
        self.states = {}
        self.pending = {}
        self.last = {}
        self.events = deque(maxlen=60)
        self.http = None

    # ---------- HA helpers ----------
    async def call(self, domain, service, data, response=False):
        url = f"{API}/services/{domain}/{service}" + ("?return_response" if response else "")
        async with self.http.post(url, json=data, headers=HDR, timeout=aiohttp.ClientTimeout(total=120)) as r:
            if r.status >= 400:
                raise RuntimeError(f"{r.status} {await r.text()}")
            return await r.json()

    async def get_state(self, eid):
        if not eid:
            return None
        async with self.http.get(f"{API}/states/{eid}", headers=HDR) as r:
            return await r.json() if r.status == 200 else None

    async def load_states(self):
        async with self.http.get(f"{API}/states", headers=HDR) as r:
            allst = await r.json()
        tracked = self.tracked_ids()
        self.states = {s["entity_id"]: {"state": s["state"], "attributes": s["attributes"]}
                       for s in allst if s["entity_id"].split(".")[0] in ("person", "device_tracker", "zone")
                       or s["entity_id"] in tracked}
        return allst

    # ---------- matching ----------
    def tracked_ids(self):
        return {p["entity_id"] for p in self.cfg["people"] if p.get("entity_id")}

    def person(self, pid):
        return next((p for p in self.cfg["people"] if p["id"] == pid), None)

    def who_ids(self, plc):
        ppl = [self.person(i) for i in plc.get("who", [])] if plc.get("who") else self.cfg["people"]
        return [p["entity_id"] for p in ppl if p and p.get("entity_id")]

    def in_zone(self, eid, zone):
        s = (self.states.get(eid) or {}).get("state", "")
        name = ((self.states.get(zone) or {}).get("attributes", {}).get("friendly_name") or "").lower()
        return s.lower() in (name, zone.split(".")[-1].lower()) and s != ""

    def satisfied(self, plc):
        vals = [self.in_zone(e, plc["zone"]) for e in self.who_ids(plc)]
        if not vals:
            return False
        return all(vals) if plc.get("mode") == "all" else any(vals)

    def name_of(self, eid):
        return next((p["name"] for p in self.cfg["people"] if p.get("entity_id") == eid), eid)

    def who_text(self, plc, trigger):
        ids = self.who_ids(plc)
        if plc.get("mode") == "all" or not trigger:
            names = [self.name_of(e) for e in ids if trigger is None or self.in_zone(e, plc["zone"])]
        else:
            names = [self.name_of(trigger)]
        return " and ".join(names) if names else "Someone"

    # ---------- events ----------
    def handle_state(self, eid, new):
        if not new or not (eid.startswith("zone.") or eid in self.tracked_ids()):
            return
        places = [p for p in self.cfg["places"] if p.get("enabled", True)]
        before = {p["id"]: self.satisfied(p) for p in places}
        self.states[eid] = {"state": new["state"], "attributes": new.get("attributes", {})}
        if eid.startswith("zone."):
            return
        for p in places:
            if eid not in self.who_ids(p):
                continue
            if self.satisfied(p) and not before[p["id"]]:
                old = self.pending.pop(p["id"], None)
                if old:
                    old.cancel()
                self.pending[p["id"]] = asyncio.create_task(self.run_place(p["id"], eid))
            elif not self.satisfied(p):
                old = self.pending.pop(p["id"], None)
                if old:
                    old.cancel()

    def blocked(self, plc):
        s = self.cfg["settings"]
        if not s.get("enabled", True):
            return "notifications are paused"
        now = datetime.now(ZoneInfo(s.get("timezone") or "America/New_York"))
        if plc.get("days") and now.weekday() not in plc["days"]:
            return "outside allowed days"
        a, b = plc.get("start"), plc.get("end")
        if a and b:
            cur = now.strftime("%H:%M")
            ok = (a <= cur <= b) if a <= b else (cur >= a or cur <= b)
            if not ok:
                return f"outside time window {a}-{b}"
        cd = float(s.get("cooldown_min") or 0) * 60
        if time.time() - self.last.get(plc["id"], 0) < cd:
            return "cooldown active"
        return None

    async def run_place(self, pid, trigger):
        try:
            plc = next((p for p in self.cfg["places"] if p["id"] == pid), None)
            if not plc:
                return
            await asyncio.sleep(int(plc.get("dwell") or 0))
            self.pending.pop(pid, None)
            if not self.satisfied(plc):
                return
            why = self.blocked(plc)
            if why:
                self.note(plc["name"], "skipped", why)
                return
            self.last[pid] = time.time()
            await self.fire(plc, trigger, send=True)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            log.exception("run_place failed")
            self.note(pid, "error", str(e))

    # ---------- message ----------
    async def generate(self, plc, who):
        s = self.cfg["settings"]
        now = datetime.now(ZoneInfo(s.get("timezone") or "America/New_York")).strftime("%A, %B %-d %Y %-I:%M %p %Z")
        ctx = await self.get_state(s.get("context_entity"))
        ctx = (ctx or {}).get("attributes", {}).get(s.get("context_attribute") or "content")
        locs = await self.get_state(s.get("locations_entity"))
        notes = "\n".join(f"- {p['name']}: {p['notes']}" for p in self.cfg["people"] if p.get("notes"))
        parts = []
        if ctx:
            parts.append(f"Here is context about the household:\n{ctx}")
        if notes:
            parts.append(f"About the people:\n{notes}")
        parts.append(f"Current date and time: {now}\nUser timezone: {s.get('timezone')}")
        if locs:
            parts.append("Our Locations: " + json.dumps(locs.get("attributes", {}), ensure_ascii=False) +
                         '\n\nUse this to understand when "tonight", "it is 5:00PM", "this morning", "Friday", etc. refers to.')
        parts.append(f"Event: {who} just arrived at {plc['name']}." + (" " + plc["extra"] if plc.get("extra") else ""))
        parts.append(plc.get("custom_prompt") or s.get("style") or DEFAULT_STYLE)
        parts.append(f"Keep it within {s.get('max_chars', 256)} characters when read.\nNo markdown, no formatting, just plain text.")
        try:
            r = await self.call("ai_task", "generate_data", {
                "task_name": f"Arrived at {plc['name']}", "instructions": "\n\n".join(parts),
                "entity_id": s["ai_entity"]}, response=True)
            text = ((r or {}).get("service_response") or {}).get("data")
            if text:
                return str(text).strip(), False
        except Exception as e:
            log.warning("AI task failed: %s", e)
        return fmt(s.get("fallback") or "{who} arrived at {place}", who, plc["name"]), True

    async def fire(self, plc, trigger, send):
        who = self.who_text(plc, trigger)
        text, fell_back = await self.generate(plc, who)
        title = fmt(plc.get("title") or "{who} arrived at {place}", who, plc["name"])
        if send:
            dom, _, svc = self.cfg["settings"]["notify_service"].partition(".")
            await self.call(dom, svc, {"title": title, "message": text})
        self.note(plc["name"], "sent" if send else "preview", text + (" (AI failed, used fallback)" if fell_back else ""))
        return {"title": title, "message": text, "fallback": fell_back}

    def note(self, place_name, kind, msg):
        self.events.appendleft({"t": datetime.now().strftime("%b %d %I:%M:%S %p"), "place": place_name,
                                "kind": kind, "msg": msg})

    # ---------- websocket ----------
    async def ws_loop(self):
        while True:
            try:
                async with self.http.ws_connect(WS, heartbeat=30) as ws:
                    await ws.receive_json()
                    await ws.send_json({"type": "auth", "access_token": TOKEN})
                    m = await ws.receive_json()
                    if m.get("type") != "auth_ok":
                        raise RuntimeError(f"auth failed: {m}")
                    await self.load_states()
                    await ws.send_json({"id": 1, "type": "subscribe_events", "event_type": "state_changed"})
                    log.info("Connected to Home Assistant")
                    async for msg in ws:
                        if msg.type != aiohttp.WSMsgType.TEXT:
                            continue
                        d = json.loads(msg.data)
                        if d.get("type") == "event":
                            ev = d["event"]["data"]
                            self.handle_state(ev["entity_id"], ev.get("new_state"))
            except Exception as e:
                log.warning("WS dropped: %s", e)
            await asyncio.sleep(10)

    # ---------- web ----------
    async def h_index(self, req):
        return web.FileResponse(INDEX)

    async def h_get_cfg(self, req):
        return web.json_response(self.cfg)

    async def h_set_cfg(self, req):
        c = await req.json()
        if not all(k in c for k in ("settings", "people", "places")):
            return web.json_response({"error": "bad config"}, status=400)
        self.cfg = c
        save_cfg(c)
        await self.load_states()
        return web.json_response({"ok": True})

    async def h_entities(self, req):
        allst = await self.load_states()
        def pick(*doms):
            return sorted(({"id": s["entity_id"], "name": s["attributes"].get("friendly_name", s["entity_id"])}
                           for s in allst if s["entity_id"].split(".")[0] in doms), key=lambda x: x["name"].lower())
        notify = []
        try:
            async with self.http.get(f"{API}/services", headers=HDR) as r:
                for d in await r.json():
                    if d["domain"] == "notify":
                        notify = sorted(f"notify.{k}" for k in d["services"] if k != "send_message")
        except Exception:
            pass
        return web.json_response({"zones": pick("zone"), "trackable": pick("person", "device_tracker", "sensor"),
                                  "ai": [x["id"] for x in pick("ai_task")], "notify": notify})

    async def h_test(self, req):
        b = await req.json()
        plc = next((p for p in self.cfg["places"] if p["id"] == b.get("id")), None)
        if not plc:
            return web.json_response({"error": "Place not found. Save first."}, status=404)
        try:
            return web.json_response(await self.fire(plc, None, send=bool(b.get("send"))))
        except Exception as e:
            return web.json_response({"error": str(e)}, status=500)

    async def h_log(self, req):
        return web.json_response(list(self.events))

async def main():
    app = App()
    app.http = aiohttp.ClientSession()
    w = web.Application()
    w.add_routes([web.get("/", app.h_index), web.get("/api/config", app.h_get_cfg),
                  web.post("/api/config", app.h_set_cfg), web.get("/api/entities", app.h_entities),
                  web.post("/api/test", app.h_test), web.get("/api/log", app.h_log)])
    runner = web.AppRunner(w)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8099).start()
    await app.ws_loop()

asyncio.run(main())
