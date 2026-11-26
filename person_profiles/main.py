import asyncio
import fnmatch
import json
import logging
import os
import re
from datetime import datetime, timezone

import aiohttp
from aiohttp import web

import profile_data as PD

OPT = json.load(open("/data/options.json"))
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
API = "http://supervisor/core/api"
WS_URL = "ws://supervisor/core/websocket"
CACHE_FILE = "/data/cache.json"
PROFILES_FILE = "/data/profiles.json"
PORT = 8099
TZ_NAME = ["UTC"]

logging.basicConfig(
    level=getattr(logging, str(OPT.get("log_level", "info")).upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("person_profiles")

_BG_TASKS: set = set()  # keep references so background tasks are not garbage-collected mid-run


def _spawn(coro):
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task



def now_iso():
    return datetime.now(timezone.utc).isoformat()


def norm(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def load_cache():
    try:
        return json.load(open(CACHE_FILE))
    except Exception:
        return {"ai": {}, "qa": {}}


def save_cache(cache):
    try:
        json.dump(cache, open(CACHE_FILE, "w"))
    except Exception as e:
        log.warning("Could not save cache: %s", e)


def load_store():
    try:
        d = json.load(open(PROFILES_FILE))
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def save_store(store):
    tmp = PROFILES_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(store, f)
    os.replace(tmp, PROFILES_FILE)


def local_today():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(TZ_NAME[0])).date()
    except Exception:
        return datetime.now().date()


def entry(store, slug):
    """What the web page saved for one person, always cleaned."""
    e = store.get(slug) or {}
    return {"data": PD.clean_data(e.get("data")), "flags": PD.clean_flags(e.get("flags")),
            "links": PD.clean_links(e.get("links")), "ignore": PD.clean_ids(e.get("ignore"))}


class HA:
    def __init__(self, session):
        self.session = session
        self.ws = None
        self.msg_id = 0
        self.pending = {}
        self.on_event = None

    async def connect(self):
        self.ws = await self.session.ws_connect(WS_URL, heartbeat=30)
        await self.ws.receive_json()
        await self.ws.send_json({"type": "auth", "access_token": TOKEN})
        reply = await self.ws.receive_json()
        if reply.get("type") != "auth_ok":
            raise RuntimeError(f"Auth failed: {reply}")

    async def reader(self):
        async for msg in self.ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            if data.get("type") == "result":
                fut = self.pending.pop(data["id"], None)
                if fut and not fut.done():
                    fut.set_result(data)
            elif data.get("type") == "event" and self.on_event:
                _spawn(self.on_event(data["event"]))

    async def call(self, payload, timeout=60):
        self.msg_id += 1
        mid = self.msg_id
        fut = asyncio.get_running_loop().create_future()
        self.pending[mid] = fut
        await self.ws.send_json({**payload, "id": mid})
        data = await asyncio.wait_for(fut, timeout)
        if not data.get("success"):
            raise RuntimeError(str(data.get("error")))
        return data.get("result")

    async def set_state(self, entity_id, state, attributes):
        url = f"{API}/states/{entity_id}"
        headers = {"Authorization": f"Bearer {TOKEN}"}
        body = {"state": str(state)[:255], "attributes": attributes}
        async with self.session.post(url, json=body, headers=headers) as r:
            if r.status >= 300:
                log.warning("Setting %s failed: %s %s", entity_id, r.status, await r.text())


def extract_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    a, b = text.find("{"), text.rfind("}")
    if a != -1 and b > a:
        try:
            return json.loads(text[a:b + 1])
        except Exception:
            return None
    return None


async def ask_ai(ha, prompt):
    task_entity = (OPT.get("ai_task_entity") or "").strip()
    agent = (OPT.get("conversation_agent") or "").strip()
    if task_entity:
        res = await ha.call({
            "type": "call_service", "domain": "ai_task", "service": "generate_data",
            "service_data": {"task_name": "person_profile", "instructions": prompt,
                             "entity_id": task_entity},
            "return_response": True}, timeout=240)
        data = ((res or {}).get("response") or {}).get("data")
        return data if isinstance(data, str) else json.dumps(data)
    if agent:
        res = await ha.call({
            "type": "call_service", "domain": "conversation", "service": "process",
            "service_data": {"text": prompt, "agent_id": agent},
            "return_response": True}, timeout=240)
        resp = ((res or {}).get("response") or {}).get("response") or {}
        return (resp.get("speech") or {}).get("plain", {}).get("speech", "")
    return None


def ai_available():
    return bool((OPT.get("ai_task_entity") or "").strip() or (OPT.get("conversation_agent") or "").strip())


class App:
    def __init__(self, ha):
        self.ha = ha
        self.cache = load_cache()
        self.lock = asyncio.Lock()
        self.reg_loaded = 0
        self.ent_reg = []
        self.dev_reg = []
        self.last_ai = {}
        self.store = load_store()

    async def load_registry(self):
        loop_time = asyncio.get_running_loop().time()
        if self.ent_reg and loop_time - self.reg_loaded < 600:
            return
        self.ent_reg = await self.ha.call({"type": "config/entity_registry/list"})
        self.dev_reg = await self.ha.call({"type": "config/device_registry/list"})
        self.reg_loaded = loop_time

    def keep(self, eid, st, reg):
        domain = eid.split(".")[0]
        if domain in OPT.get("exclude_domains", []):
            return False
        if eid.startswith("sensor.person_profile"):
            return False
        for pat in OPT.get("exclude_entity_patterns", []):
            if fnmatch.fnmatch(eid, pat):
                return False
        if reg and reg.get("disabled_by"):
            return False
        if st is None:
            return False
        if not OPT.get("include_unavailable") and st["state"] in ("unavailable", "unknown"):
            return False
        return True

    async def collect(self):
        await self.load_registry()
        states = {s["entity_id"]: s for s in await self.ha.call({"type": "get_states"})}
        reg_by_entity = {e["entity_id"]: e for e in self.ent_reg}
        by_device = {}
        for e in self.ent_reg:
            if e.get("device_id"):
                by_device.setdefault(e["device_id"], []).append(e["entity_id"])
        wanted = set(OPT.get("people") or [])
        extras = {x["person"]: x.get("entities", []) for x in OPT.get("person_extras", [])}
        profiles = {}
        for pid, pst in states.items():
            if not pid.startswith("person."):
                continue
            if wanted and pid not in wanted:
                continue
            attrs = pst.get("attributes", {})
            name = attrs.get("friendly_name") or pid.split(".")[1]
            slug = pid.split(".")[1]
            trackers = attrs.get("device_trackers") or []
            related = {}
            for t in trackers:
                related[t] = "tracker"
                dev = (reg_by_entity.get(t) or {}).get("device_id")
                if dev:
                    for e in by_device.get(dev, []):
                        related.setdefault(e, "same device as tracker")
            for e in extras.get(pid, []):
                related.setdefault(e, "manual")
            mine = entry(self.store, slug)
            link_labels = {l["entity_id"]: l["label"] for l in mine["links"]}
            for l in mine["links"]:
                related[l["entity_id"]] = "linked in web page"
            if OPT.get("name_matching", True):
                tokens = {norm(slug), norm(name), norm(name.split(" ")[0])}
                tokens = {t for t in tokens if len(t) >= 3}
                for eid, st in states.items():
                    if eid == pid or eid in related:
                        continue
                    hay_id = norm(eid.split(".", 1)[1])
                    hay_name = norm(st.get("attributes", {}).get("friendly_name", ""))
                    if any(t in hay_id or t in hay_name for t in tokens):
                        related[eid] = "name match"
            ents = []
            for eid, why in related.items():
                st = states.get(eid)
                if eid in mine["ignore"] and eid not in link_labels:
                    continue
                if why != "linked in web page" and not self.keep(eid, st, reg_by_entity.get(eid)):
                    continue
                if st is None:
                    continue
                a = st.get("attributes", {})
                ents.append({
                    "entity_id": eid,
                    "name": link_labels.get(eid) or a.get("friendly_name", eid),
                    "state": st["state"],
                    "unit": a.get("unit_of_measurement", ""),
                    "device_class": a.get("device_class", ""),
                    "why": why,
                })
            ents.sort(key=lambda x: (x["why"] != "linked in web page", x["why"] != "tracker", x["entity_id"]))
            profiles[slug] = {
                "entity_id": pid, "slug": slug, "name": name, "state": pst["state"],
                "attrs": attrs, "trackers": {t: states.get(t, {}).get("state", "unknown") for t in trackers},
                "entities": ents, "mine": mine,
            }
        return profiles

    def data_text(self, p):
        lines = [f"Person: {p['name']} ({p['entity_id']}), location state: {p['state']}"]
        mine = p.get("mine") or {}
        known = PD.profile_text(mine.get("data", {}), mine.get("flags", {}), "ai")
        today = local_today()
        calc = PD.worked_out(mine.get("data", {}), today)
        lines.append(f"Today is {today.isoformat()}.")
        if known:
            lines.append("\nWhat the household told us about them (trust this over guesses):\n" + known)
        if calc.get("age") is not None:
            lines.append(f"Age {calc['age']}, {calc['zodiac']}, birthday in {calc['days_until_birthday']} days.")
        if calc.get("dates_next_30_days"):
            lines.append("Coming up: " + "; ".join(f"{e['label']} in {e['days_until']} days" for e in calc["dates_next_30_days"]))
        lines.append("\nLive Home Assistant data:")
        for e in p["entities"][: int(OPT.get("max_entities_for_ai", 150))]:
            lines.append(f"- {e['name']} ({e['entity_id']}): {e['state']} {e['unit']}".rstrip())
        return "\n".join(lines)

    async def run_ai_summary(self, p):
        prompt = (
            "You are building a short profile of one household member from Home Assistant data.\n"
            f"Current time (UTC): {now_iso()}\n{self.data_text(p)}\n\n"
            "Reply ONLY with JSON in this shape: "
            '{"summary": "1-2 sentences, max 200 characters", '
            '"facts": ["short fact", "..."], "routine": "short text about patterns you can see, or empty"}. '
            "Max 8 facts. Use only the data above. Do not invent anything.\n"
            + (OPT.get("ai_extra_prompt") or "")
        )
        text = await ask_ai(self.ha, prompt)
        if not text:
            return
        parsed = extract_json(text)
        if not isinstance(parsed, dict):
            parsed = {"summary": text.strip()[:200], "facts": [], "routine": ""}
        self.cache["ai"][p["slug"]] = {
            "summary": str(parsed.get("summary", ""))[:255],
            "facts": [str(f) for f in (parsed.get("facts") or [])][:8],
            "routine": str(parsed.get("routine", ""))[:500],
            "updated": now_iso(),
        }
        save_cache(self.cache)

    def simple_summary(self, p):
        parts = [f"{p['name']}: {p['state']}"]
        battery = self.battery(p)
        if battery is not None:
            parts.append(f"battery {battery}%")
        return ", ".join(parts)

    def battery(self, p):
        for e in p["entities"]:
            if e["device_class"] == "battery" and e["entity_id"].startswith("sensor."):
                try:
                    return round(float(e["state"]))
                except ValueError:
                    continue
        return None

    async def publish(self, p):
        a = p["attrs"]
        ai = self.cache["ai"].get(p["slug"], {})
        qa = self.cache["qa"].get(p["slug"], {})
        cap = int(OPT.get("max_entities_in_sensor", 60))
        attributes = {
            "friendly_name": f"{p['name']} Profile",
            "icon": "mdi:account-details",
            "person_entity": p["entity_id"],
            "name": p["name"],
            "location": p["state"],
            "latitude": a.get("latitude"),
            "longitude": a.get("longitude"),
            "gps_accuracy": a.get("gps_accuracy"),
            "source": a.get("source"),
            "user_id": a.get("user_id"),
            "battery": self.battery(p),
            "trackers": p["trackers"],
            "entity_count": len(p["entities"]),
            "entities": {e["entity_id"]: {"name": e["name"], "state": f"{e['state']} {e['unit']}".strip()}
                         for e in p["entities"][:cap]},
            "ai_summary": ai.get("summary", ""),
            "ai_facts": ai.get("facts", []),
            "ai_routine": ai.get("routine", ""),
            "ai_updated": ai.get("updated", ""),
            "last_question": qa.get("question", ""),
            "last_answer": qa.get("answer", ""),
            "last_answer_time": qa.get("time", ""),
            "last_updated": now_iso(),
        }
        mine = p.get("mine") or {"data": {}, "flags": {}}
        calc = PD.worked_out(mine["data"], local_today())
        attributes.update({k: v for k, v in calc.items() if v is not None})
        attributes["profile"] = PD.sensor_profile(mine["data"], mine["flags"])
        attributes["profile_complete_percent"] = PD.completeness(mine["data"])
        pic = (mine["data"].get("about") or {}).get("photo")
        if a.get("entity_picture"):
            attributes["entity_picture"] = a["entity_picture"]
        elif pic:
            attributes["entity_picture"] = pic
        await self.ha.set_state(f"sensor.person_profile_{p['slug']}", self.simple_summary(p), attributes)

    async def cycle(self, force_ai=False, only=None):
        async with self.lock:
            profiles = await self.collect()
            interval = int(OPT.get("ai_interval_minutes", 60))
            loop_time = asyncio.get_running_loop().time()
            for slug, p in profiles.items():
                if only and only not in (slug, p["entity_id"]):
                    continue
                due = interval > 0 and loop_time - self.last_ai.get(slug, -1e9) >= interval * 60
                if ai_available() and (force_ai or due):
                    try:
                        self.last_ai[slug] = loop_time
                        await self.run_ai_summary(p)
                    except Exception as e:
                        log.warning("AI summary failed for %s: %s", slug, e)
                await self.publish(p)
            summary = {s: self.cache["ai"].get(s, {}).get("summary") or self.simple_summary(p)
                       for s, p in profiles.items()}
            await self.ha.set_state("sensor.person_profiles", len(profiles), {
                "friendly_name": "Person Profiles", "icon": "mdi:account-multiple",
                "profiles": summary, "last_updated": now_iso()})

    async def answer(self, data):
        who = str(data.get("person", "")).replace("person.", "")
        question = str(data.get("question", "")).strip()
        if not who or not question:
            log.warning("person_profile_ask needs person and question")
            return
        if not ai_available():
            log.warning("No AI entity configured for questions")
            return
        async with self.lock:
            profiles = await self.collect()
            p = profiles.get(who)
            if not p:
                log.warning("Unknown person %s", who)
                return
            prompt = (
                f"Answer a question about {p['name']} using only this Home Assistant data. "
                "If the data does not say, answer that you do not know. Keep it short.\n"
                f"Current time (UTC): {now_iso()}\n{self.data_text(p)}\n\nQuestion: {question}\n"
                + (OPT.get("ai_extra_prompt") or "")
            )
            try:
                answer = (await ask_ai(self.ha, prompt) or "").strip()
            except Exception as e:
                answer = f"AI error: {e}"
            self.cache["qa"][who] = {"question": question, "answer": answer[:1000], "time": now_iso()}
            save_cache(self.cache)
            await self.publish(p)
            await self.ha.call({"type": "fire_event", "event_type": "person_profile_answer",
                                "event_data": {"person": p["entity_id"], "question": question,
                                               "answer": answer, "request_id": data.get("request_id")}})

    async def on_event(self, ev):
        etype, data = ev.get("event_type"), ev.get("data") or {}
        try:
            if etype == "person_profile_refresh":
                await self.cycle(force_ai=bool(data.get("ai")), only=data.get("person"))
            elif etype == "person_profile_ask":
                await self.answer(data)
        except Exception as e:
            log.warning("Event %s failed: %s", etype, e)



CUR = {"app": None}
INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html")


def jerr(msg, status=400):
    return web.json_response({"error": msg}, status=status)


async def h_index(request):
    return web.FileResponse(INDEX, headers={"Cache-Control": "no-store"})


async def h_schema(request):
    return web.json_response(PD.schema())


async def h_people(request):
    app = CUR["app"]
    if not app:
        return jerr("Still connecting to Home Assistant, try again in a few seconds", 503)
    states = await app.ha.call({"type": "get_states"})
    wanted = set(OPT.get("people") or [])
    out = []
    for s in states:
        eid = s["entity_id"]
        if not eid.startswith("person.") or (wanted and eid not in wanted):
            continue
        slug = eid.split(".")[1]
        e = entry(app.store, slug)
        out.append({"slug": slug, "entity_id": eid, "name": s["attributes"].get("friendly_name") or slug,
                    "state": s["state"], "picture": s["attributes"].get("entity_picture", ""),
                    "complete": PD.completeness(e["data"])})
    out.sort(key=lambda x: x["name"].lower())
    return web.json_response({"people": out, "ai": ai_available()})


async def h_profile_get(request):
    app = CUR["app"]
    if not app:
        return jerr("Still connecting to Home Assistant", 503)
    slug = request.match_info["slug"]
    profiles = await app.collect()
    p = profiles.get(slug)
    if not p:
        return jerr("No such person", 404)
    mine = p["mine"]
    return web.json_response({
        "slug": slug, "name": p["name"], "entity_id": p["entity_id"], "state": p["state"],
        "data": mine["data"], "flags": mine["flags"], "links": mine["links"], "ignore": mine["ignore"],
        "worked_out": PD.worked_out(mine["data"], local_today()),
        "complete": PD.completeness(mine["data"]),
        "entities": [{k: e[k] for k in ("entity_id", "name", "state", "unit", "why")} for e in p["entities"]],
        "ai": app.cache["ai"].get(slug, {}), "ai_available": ai_available()})


async def h_profile_save(request):
    app = CUR["app"]
    if not app:
        return jerr("Still connecting to Home Assistant", 503)
    slug = request.match_info["slug"]
    try:
        body = await request.json()
    except Exception:
        return jerr("That was not valid JSON")
    new = {"data": PD.clean_data(body.get("data")), "flags": PD.clean_flags(body.get("flags")),
           "links": PD.clean_links(body.get("links")), "ignore": PD.clean_ids(body.get("ignore"))}
    app.store[slug] = new
    try:
        save_store(app.store)
    except Exception as e:
        return jerr("Could not save: %s" % e, 500)
    profiles = await app.collect()
    if slug in profiles:
        await app.publish(profiles[slug])
    return web.json_response({"ok": True, "complete": PD.completeness(new["data"]),
                              "worked_out": PD.worked_out(new["data"], local_today())})


async def h_ai(request):
    app = CUR["app"]
    if not app:
        return jerr("Still connecting to Home Assistant", 503)
    if not ai_available():
        return jerr("Set ai_task_entity (or conversation_agent) in the add-on Configuration first")
    slug = request.match_info["slug"]
    await app.cycle(force_ai=True, only=slug)
    return web.json_response({"ok": True, "ai": app.cache["ai"].get(slug, {})})


async def h_entities(request):
    app = CUR["app"]
    if not app:
        return jerr("Still connecting to Home Assistant", 503)
    q = request.query.get("q", "").strip().lower()
    states = await app.ha.call({"type": "get_states"})
    out = []
    for s in states:
        eid = s["entity_id"]
        if eid.startswith("sensor.person_profile") or eid.split(".")[0] in ("update", "tts", "stt"):
            continue
        name = s["attributes"].get("friendly_name", eid)
        if q and q not in eid.lower() and q not in name.lower():
            continue
        out.append({"entity_id": eid, "name": name, "state": s["state"],
                    "unit": s["attributes"].get("unit_of_measurement", "")})
        if len(out) >= 60:
            break
    return web.json_response(out)


async def start_web():
    w = web.Application(client_max_size=1024 * 1024)
    w.add_routes([web.get("/", h_index), web.get("/api/schema", h_schema), web.get("/api/people", h_people),
                  web.get("/api/profile/{slug}", h_profile_get), web.post("/api/profile/{slug}", h_profile_save),
                  web.post("/api/ai/{slug}", h_ai), web.get("/api/entities", h_entities)])
    runner = web.AppRunner(w)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()
    log.info("Web page on port %s (open it from the sidebar)", PORT)


async def session_loop(session):
    ha = HA(session)
    await ha.connect()
    app = App(ha)
    ha.on_event = app.on_event
    reader = asyncio.create_task(ha.reader())
    for t in ("person_profile_refresh", "person_profile_ask"):
        await ha.call({"type": "subscribe_events", "event_type": t})
    try:
        cfg = await ha.call({"type": "get_config"}, timeout=15)
        TZ_NAME[0] = (cfg or {}).get("time_zone") or "UTC"
    except Exception as e:
        log.warning("Could not read the time zone (%s), using UTC for dates", repr(e))
    CUR["app"] = app
    log.info("Connected to Home Assistant")
    if not ai_available():
        log.warning("No ai_task_entity or conversation_agent set: AI summaries are off")
    interval = int(OPT.get("update_interval_seconds", 60))
    while True:
        if reader.done():
            raise RuntimeError("Websocket closed")
        await app.cycle()
        await asyncio.sleep(interval)


async def main():
    await start_web()
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                await session_loop(session)
            except Exception as e:
                log.error("Connection problem: %s. Retrying in 15s", e)
                await asyncio.sleep(15)


asyncio.run(main())
