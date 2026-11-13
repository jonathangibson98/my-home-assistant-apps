import asyncio
import fnmatch
import json
import logging
import os
import re
from datetime import datetime, timezone

import aiohttp

OPT = json.load(open("/data/options.json"))
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
API = "http://supervisor/core/api"
WS_URL = "ws://supervisor/core/websocket"
CACHE_FILE = "/data/cache.json"

logging.basicConfig(
    level=getattr(logging, str(OPT.get("log_level", "info")).upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger("person_profiles")


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
                asyncio.create_task(self.on_event(data["event"]))

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
                if not self.keep(eid, st, reg_by_entity.get(eid)):
                    continue
                a = st.get("attributes", {})
                ents.append({
                    "entity_id": eid,
                    "name": a.get("friendly_name", eid),
                    "state": st["state"],
                    "unit": a.get("unit_of_measurement", ""),
                    "device_class": a.get("device_class", ""),
                    "why": why,
                })
            ents.sort(key=lambda x: (x["why"] != "tracker", x["entity_id"]))
            profiles[slug] = {
                "entity_id": pid, "slug": slug, "name": name, "state": pst["state"],
                "attrs": attrs, "trackers": {t: states.get(t, {}).get("state", "unknown") for t in trackers},
                "entities": ents,
            }
        return profiles

    def data_text(self, p):
        lines = [f"Person: {p['name']} ({p['entity_id']}), location state: {p['state']}"]
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
        a = p["attrs"]
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
        if a.get("entity_picture"):
            attributes["entity_picture"] = a["entity_picture"]
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


async def session_loop(session):
    ha = HA(session)
    await ha.connect()
    app = App(ha)
    ha.on_event = app.on_event
    reader = asyncio.create_task(ha.reader())
    for t in ("person_profile_refresh", "person_profile_ask"):
        await ha.call({"type": "subscribe_events", "event_type": t})
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
    async with aiohttp.ClientSession() as session:
        while True:
            try:
                await session_loop(session)
            except Exception as e:
                log.error("Connection problem: %s. Retrying in 15s", e)
                await asyncio.sleep(15)


asyncio.run(main())
