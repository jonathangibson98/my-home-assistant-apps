#!/usr/bin/env python3
"""AI Builder - turns plain-English requests into Home Assistant config using an ai_task entity."""
import asyncio
import json
import logging
import os
import re
import time
from collections import Counter
from pathlib import Path

import aiohttp
import yaml
from aiohttp import web

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ai_builder")

TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
API = "http://supervisor/core/api"
WS_URL = "ws://supervisor/core/websocket"
HDR = {"Authorization": f"Bearer {TOKEN}"}

try:
    OPTS = json.load(open("/data/options.json"))
except Exception:
    OPTS = {}
ENTITY = OPTS.get("ai_task_entity") or "ai_task.gemini_pro_ai_task"
TIMEOUT = int(OPTS.get("request_timeout") or 180)

CONF = Path("/homeassistant")
PKG_DIR = CONF / "ai_builder"
PKG_FILE = PKG_DIR / "package.yaml"
STORE = Path("/data/templates.json")
HIST = Path("/data/history.json")
INDEX = Path("/app/index.html")

HELPER_FIELDS = {
    "input_boolean": ["name", "icon", "initial"],
    "input_number": ["name", "icon", "min", "max", "step", "mode", "unit_of_measurement", "initial"],
    "input_select": ["name", "icon", "options", "initial"],
    "input_text": ["name", "icon", "min", "max", "mode", "pattern", "initial"],
    "input_datetime": ["name", "icon", "has_date", "has_time", "initial"],
    "counter": ["name", "icon", "initial", "step", "minimum", "maximum", "restore"],
    "timer": ["name", "icon", "duration", "restore"],
}
PRIORITY = {"helper": 0, "template": 1, "script": 2, "automation": 3}
STOP = set(
    "the and for with that this when then from have has are was will into your you our out any all "
    "turn make create set can please want need would like should every each".split()
)
ENT_RE = re.compile(r"\b([a-z_]+)\.([a-z0-9_]+)\b")


# ---------------------------------------------------------------- helpers
def slug(s):
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_")


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def save_json(path, data):
    path.write_text(json.dumps(data, indent=2))


def errmsg(data):
    if isinstance(data, dict):
        return str(data.get("message") or data.get("error") or json.dumps(data))[:600]
    return str(data)[:600]


async def ha(app, method, path, body=None, params=None, timeout=30, raw=False):
    try:
        async with app["http"].request(
            method, API + path, json=body, params=params, headers=HDR,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as r:
            txt = await r.text()
            if raw:
                return r.status, txt
            try:
                return r.status, json.loads(txt)
            except ValueError:
                return r.status, txt
    except asyncio.TimeoutError:
        return 0, "Timed out waiting for Home Assistant"
    except aiohttp.ClientError as e:
        return 0, f"Could not reach Home Assistant: {e}"


async def ws_call(app, msg):
    async with app["http"].ws_connect(WS_URL) as ws:
        await ws.receive_json()
        await ws.send_json({"type": "auth", "access_token": TOKEN})
        r = await ws.receive_json()
        if r.get("type") != "auth_ok":
            raise RuntimeError("WebSocket auth failed")
        msg["id"] = 1
        await ws.send_json(msg)
        while True:
            r = await ws.receive_json()
            if r.get("id") == 1:
                return r


def render_package(store):
    sensors, binaries = [], []
    for e in store.values():
        d = {"name": e["name"], "unique_id": e["unique_id"], "state": e["state"]}
        keys = ["device_class", "icon", "availability"]
        if e["platform"] == "sensor":
            keys += ["unit_of_measurement", "state_class"]
        for k in keys:
            if e.get(k):
                d[k] = e[k]
        if e.get("attributes"):
            d["attributes"] = e["attributes"]
        (binaries if e["platform"] == "binary_sensor" else sensors).append(d)
    block = {}
    if sensors:
        block["sensor"] = sensors
    if binaries:
        block["binary_sensor"] = binaries
    pkg = {"template": [block] if block else []}
    PKG_DIR.mkdir(parents=True, exist_ok=True)
    header = "# Managed by the AI Builder add-on. Edits here get overwritten.\n"
    PKG_FILE.write_text(header + yaml.safe_dump(pkg, sort_keys=False, allow_unicode=True, width=1000))


def package_included():
    try:
        return "ai_builder/package.yaml" in (CONF / "configuration.yaml").read_text()
    except Exception:
        return False


def add_history(entry):
    h = load_json(HIST, [])
    h.insert(0, {**entry, "time": time.strftime("%Y-%m-%d %H:%M")})
    save_json(HIST, h[:40])


# ---------------------------------------------------------------- AI prompt
def tokens(text):
    out = set()
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if len(w) < 3 or w in STOP:
            continue
        out.add(w)
        if w.endswith("s") and len(w) > 3:
            out.add(w[:-1])
    return out


def build_context(states, services, text):
    toks = tokens(text)
    scored = []
    for s in states:
        eid = s["entity_id"]
        name = (s.get("attributes") or {}).get("friendly_name", "") or ""
        hay = f"{eid} {name}".lower()
        score = sum(1 for t in toks if t in hay)
        if score:
            scored.append((score, eid, name, str(s["state"])[:30]))
    scored.sort(key=lambda x: (-x[0], x[1]))
    relevant = [f"{e} | {n} | {st}" for _, e, n, st in scored[:70]]

    always_domains = {"person", "zone", "input_boolean", "input_number", "input_select",
                      "input_text", "input_datetime", "timer", "counter", "ai_task"}
    always = []
    for s in states:
        if s["entity_id"].split(".")[0] in always_domains:
            n = (s.get("attributes") or {}).get("friendly_name", "") or ""
            always.append(f"{s['entity_id']} | {n} | {str(s['state'])[:30]}")
    domains = Counter(s["entity_id"].split(".")[0] for s in states)
    notify = sorted(k for k in services if k.startswith("notify."))
    return (
        "ENTITIES MOST RELEVANT TO THE REQUEST (entity_id | name | state):\n" + "\n".join(relevant or ["(none matched)"])
        + "\n\nPEOPLE, ZONES AND HELPERS:\n" + "\n".join(always[:80] or ["(none)"])
        + "\n\nNOTIFY SERVICES: " + ", ".join(notify[:40])
        + "\n\nENTITY COUNT BY DOMAIN: " + ", ".join(f"{d}={c}" for d, c in domains.most_common(30))
    )


RULES = """You are an expert Home Assistant configuration engineer. Home Assistant version: {version}. Temperature unit: {unit}. Time zone: {tz}.
The person asking is NOT a programmer, so write the summary in plain English.

Reply with ONE JSON object and nothing else (no markdown fences, no commentary):
{{
  "summary": "1-3 plain-English sentences describing what you built",
  "warnings": ["anything the person should know or double-check"],
  "items": [ {{"kind": "...", "summary": "what this item does", "id": "...", "config": {{...}} }} ]
}}

Item kinds and their config:
- "automation": modern syntax. Keys: alias, description, mode, triggers (each with "trigger": "state|numeric_state|time|time_pattern|sun|zone|event|template|..."), conditions (each with "condition": ...), actions (each with "action": "domain.service" or other action types like choose/if/delay/repeat/wait_for_trigger). Example:
  {{"alias":"Fan on when hot","description":"","mode":"single","triggers":[{{"trigger":"numeric_state","entity_id":"sensor.x","above":76}}],"conditions":[],"actions":[{{"action":"fan.turn_on","target":{{"entity_id":"fan.y"}}}}]}}
- "script": top-level "id" is a snake_case slug. config keys: alias, description, mode, sequence (list of actions).
- "template": a template sensor or binary sensor. config keys: platform ("sensor" or "binary_sensor"), name, unique_id (snake_case), state (a Jinja template string), and optionally unit_of_measurement, device_class, state_class (sensors only), icon, availability (template), attributes (object of name -> template string). Binary sensor state must render to true or false. Use filters like | float(0) and default values so it never errors.
- "helper": config keys: type (one of input_boolean, input_number, input_select, input_text, input_datetime, counter, timer), name, and the fields that type needs (input_number: min, max, step, mode, unit_of_measurement; input_select: options list; input_datetime: has_date, has_time; timer: duration like "00:05:00"; etc).
- "answer": use when the person asked a question, the request is unclear, or it cannot be done. config: {{"text": "your answer"}}.

Rules:
- A request can need several items (for example helpers + a template sensor + an automation). Return all of them in "items".
- Use ONLY entity_ids from the lists below. If something needed is missing, still write the config with your best guess and add a warning naming the missing entity.
- Only use real Home Assistant actions (services). Never invent any.
- Prefer built-in features over complicated templates. Keep it simple and reliable.
- Notifications: use a notify service from the list when one fits.
"""


def build_prompt(text, kind, ctx, existing, target, previous, feedback, cfg):
    p = RULES.format(
        version=cfg.get("version", "recent"),
        unit=(cfg.get("unit_system") or {}).get("temperature", "unknown"),
        tz=cfg.get("time_zone", "unknown"),
    )
    if kind and kind != "auto":
        p += f"\nThe person specifically wants this built as: {kind}.\n"
    p += "\n" + ctx + "\n"
    if existing is not None and target:
        p += (
            f"\nTHE PERSON IS EDITING AN EXISTING {target['kind'].upper()} (id: {target['id']}). Current config:\n"
            + json.dumps(existing, indent=1)
            + "\nApply their change and return the FULL updated config as a single item of the same kind. "
            "Keep everything they did not ask to change.\n"
        )
    p += f"\nREQUEST FROM THE PERSON:\n{text}\n"
    if previous:
        p += (
            "\nYOUR PREVIOUS ANSWER:\n" + json.dumps(previous, indent=1)
            + f"\n\nTHE PERSON'S FEEDBACK / THE PROBLEM TO FIX:\n{feedback}\n"
            "Return the complete corrected JSON object (all items), not just the changes.\n"
        )
    return p


def extract_json(t):
    t = (t or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I).strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        return json.loads(t[i : j + 1])
    raise ValueError("no JSON found")


async def ask_ai(app, prompt):
    st, data = await ha(
        app, "POST", "/services/ai_task/generate_data",
        {"entity_id": ENTITY, "task_name": "ha_builder", "instructions": prompt},
        params={"return_response": "true"}, timeout=TIMEOUT,
    )
    if st != 200:
        raise RuntimeError(f"AI task call failed: {errmsg(data)}")
    sr = data.get("service_response") if isinstance(data, dict) else None
    out = (sr or {}).get("data")
    if out is None:
        return ""
    return out if isinstance(out, str) else json.dumps(out)


# ---------------------------------------------------------------- checks
def find_unknown(config, known_ids, domains, services):
    found = set()

    def walk(x):
        if isinstance(x, str):
            for m in ENT_RE.finditer(x.replace("states.", "")):
                full = m.group(0)
                if m.group(1) in domains and full not in known_ids and full not in services:
                    found.add(full)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk(config)
    return sorted(found)


def normalize(parsed, target):
    if isinstance(parsed, list):
        parsed = {"items": parsed}
    items = parsed.get("items")
    if items is None and "config" in parsed:
        items = [parsed]
    items = [i for i in (items or []) if isinstance(i, dict)]
    out, used_target = [], False
    for it in items:
        kind = str(it.get("kind", "")).lower().replace(" ", "_")
        if kind in ("template_sensor", "template_entity", "template_binary_sensor"):
            kind = "template"
        if kind not in PRIORITY and kind != "answer":
            kind = "answer"
        cfg = it.get("config") if isinstance(it.get("config"), dict) else {}
        item = {"kind": kind, "summary": it.get("summary", ""), "id": it.get("id"), "config": cfg}
        if target and not used_target and kind == target["kind"]:
            used_target = True
            if kind == "automation":
                item["edit_id"] = target["id"]
            elif kind == "script":
                item["id"] = target["id"]
            elif kind == "template":
                cfg["unique_id"] = target["id"]
        out.append(item)
    return {"summary": parsed.get("summary", ""), "warnings": parsed.get("warnings") or [], "items": out}


async def enrich(app, result, states, services):
    known = {s["entity_id"] for s in states}
    domains = {e.split(".")[0] for e in known}
    for it in result["items"]:
        it["checks"] = {"unknown": [], "preview": None, "error": None}
        if it["kind"] == "answer":
            continue
        it["yaml"] = yaml.safe_dump(it["config"], sort_keys=False, allow_unicode=True, width=100)
        it["checks"]["unknown"] = find_unknown(it["config"], known, domains, services)
        if it["kind"] == "template" and it["config"].get("state"):
            st, txt = await ha(app, "POST", "/template", {"template": str(it["config"]["state"])}, raw=True)
            if st == 200:
                it["checks"]["preview"] = txt.strip()[:200]
            else:
                it["checks"]["error"] = txt.strip()[:400]
    return result


async def load_target(app, kind, tid):
    if kind == "automation":
        st, d = await ha(app, "GET", f"/config/automation/config/{tid}")
    elif kind == "script":
        st, d = await ha(app, "GET", f"/config/script/config/{tid}")
    elif kind == "template":
        d = load_json(STORE, {}).get(tid)
        return d if d else None
    else:
        return None
    if st != 200:
        raise RuntimeError(f"Could not load that {kind} (it may be defined in YAML): {errmsg(d)}")
    return d


# ---------------------------------------------------------------- routes
async def index(request):
    return web.Response(text=INDEX.read_text(), content_type="text/html")


async def status(request):
    app = request.app
    st, states = await ha(app, "GET", "/states")
    st2, cfg = await ha(app, "GET", "/config")
    ai_ok = isinstance(states, list) and any(s["entity_id"] == ENTITY for s in states)
    return web.json_response({
        "entity": ENTITY,
        "entity_found": ai_ok,
        "ha_ok": st == 200,
        "version": cfg.get("version") if isinstance(cfg, dict) else None,
        "package_included": package_included(),
    })


async def generate(request):
    app = request.app
    b = await request.json()
    text = (b.get("request") or "").strip()
    feedback = (b.get("feedback") or "").strip()
    if not text:
        return web.json_response({"error": "Type what you want first."})
    target = b.get("target") or None
    previous = b.get("previous") or None

    st, states = await ha(app, "GET", "/states")
    if st != 200 or not isinstance(states, list):
        return web.json_response({"error": f"Could not read Home Assistant states: {errmsg(states)}"})
    st, svc = await ha(app, "GET", "/services")
    services = set()
    if isinstance(svc, list):
        for d in svc:
            for s in (d.get("services") or {}):
                services.add(f"{d['domain']}.{s}")
    st, cfg = await ha(app, "GET", "/config")
    cfg = cfg if isinstance(cfg, dict) else {}

    existing = None
    if target:
        try:
            existing = await load_target(app, target["kind"], target["id"])
        except Exception as e:
            return web.json_response({"error": str(e)})

    ctx = build_context(states, services, text + " " + feedback)
    prompt = build_prompt(text, b.get("kind", "auto"), ctx, existing, target, previous, feedback, cfg)

    parsed, last_raw = None, ""
    for attempt in range(2):
        try:
            last_raw = await ask_ai(app, prompt if attempt == 0 else
                                    prompt + "\n\nYour last reply was not valid JSON. Reply with ONLY the JSON object.")
            parsed = extract_json(last_raw)
            break
        except ValueError:
            log.warning("AI reply was not JSON (attempt %s)", attempt + 1)
        except Exception as e:
            return web.json_response({"error": str(e)})
    if parsed is None:
        return web.json_response({"error": "The AI answered, but not in a usable format. Try again or reword it.",
                                  "raw": last_raw[:1500]})
    result = normalize(parsed, target)
    if not result["items"]:
        return web.json_response({"error": "The AI didn't return anything to build.", "raw": last_raw[:1500]})
    result = await enrich(app, result, states, services)
    return web.json_response(result)


async def create_automation(app, it):
    cfg = dict(it["config"])
    aid = str(it.get("edit_id") or int(time.time() * 1000))
    cfg["id"] = aid
    cfg.setdefault("alias", "AI automation")
    cfg.setdefault("mode", "single")
    st, d = await ha(app, "POST", f"/config/automation/config/{aid}", cfg)
    if st != 200:
        raise RuntimeError(errmsg(d))
    entity = None
    for _ in range(4):
        await asyncio.sleep(1)
        _, states = await ha(app, "GET", "/states")
        for s in states if isinstance(states, list) else []:
            if s["entity_id"].startswith("automation.") and (s.get("attributes") or {}).get("id") == aid:
                entity = s["entity_id"]
        if entity:
            break
    return {"entity": entity, "name": cfg["alias"]}


async def create_script(app, it):
    cfg = dict(it["config"])
    cfg.pop("id", None)
    cfg.setdefault("alias", "AI script")
    sid = slug(it.get("id") or cfg["alias"])
    st, d = await ha(app, "POST", f"/config/script/config/{sid}", cfg)
    if st != 200:
        raise RuntimeError(errmsg(d))
    return {"entity": f"script.{sid}", "name": cfg["alias"]}


async def create_template(app, it):
    cfg = it["config"]
    platform = cfg.get("platform", "sensor")
    if platform not in ("sensor", "binary_sensor"):
        raise RuntimeError("Template platform must be sensor or binary_sensor")
    if not cfg.get("name") or not cfg.get("state"):
        raise RuntimeError("Template needs a name and a state template")
    uid = slug(cfg.get("unique_id") or cfg["name"])
    entry = {"platform": platform, "name": cfg["name"], "unique_id": uid, "state": str(cfg["state"])}
    for k in ("unit_of_measurement", "device_class", "state_class", "icon", "availability", "attributes"):
        if cfg.get(k):
            entry[k] = cfg[k]
    store = load_json(STORE, {})
    store[uid] = entry
    save_json(STORE, store)
    render_package(store)
    st, d = await ha(app, "POST", "/services/template/reload", {})
    if st != 200:
        raise RuntimeError(f"Saved, but template reload failed: {errmsg(d)}")
    return {"entity": f"{platform}.{slug(cfg['name'])}", "name": cfg["name"], "needs_setup": not package_included()}


async def create_helper(app, it):
    cfg = it["config"]
    t = cfg.get("type")
    if t not in HELPER_FIELDS:
        raise RuntimeError(f"Unsupported helper type: {t}")
    fields = {k: cfg[k] for k in HELPER_FIELDS[t] if k in cfg}
    if "name" not in fields:
        raise RuntimeError("Helper needs a name")
    r = await ws_call(app, {"type": f"{t}/create", **fields})
    if not r.get("success"):
        raise RuntimeError((r.get("error") or {}).get("message", "Helper creation failed"))
    hid = (r.get("result") or {}).get("id") or slug(fields["name"])
    return {"entity": f"{t}.{hid}", "name": fields["name"]}


async def create(request):
    app = request.app
    b = await request.json()
    it = b.get("item") or {}
    kind = it.get("kind")
    fn = {"automation": create_automation, "script": create_script,
          "template": create_template, "helper": create_helper}.get(kind)
    if not fn:
        return web.json_response({"ok": False, "error": "Nothing to create for this item."})
    try:
        res = await fn(app, it)
    except Exception as e:
        log.exception("create failed")
        return web.json_response({"ok": False, "error": str(e)})
    add_history({"kind": kind, "name": res.get("name"), "entity": res.get("entity")})
    return web.json_response({"ok": True, **res})


async def targets(request):
    app = request.app
    _, states = await ha(app, "GET", "/states")
    out = []
    for s in states if isinstance(states, list) else []:
        d, _, rest = s["entity_id"].partition(".")
        a = s.get("attributes") or {}
        name = a.get("friendly_name") or s["entity_id"]
        if d == "automation" and a.get("id"):
            out.append({"kind": "automation", "id": a["id"], "name": name})
        elif d == "script":
            out.append({"kind": "script", "id": rest, "name": name})
    for uid, e in load_json(STORE, {}).items():
        out.append({"kind": "template", "id": uid, "name": e["name"]})
    out.sort(key=lambda x: (x["kind"], x["name"].lower()))
    return web.json_response(out)


async def mine(request):
    store = load_json(STORE, {})
    return web.json_response({
        "templates": [{"id": k, "name": v["name"], "platform": v["platform"]} for k, v in store.items()],
        "history": load_json(HIST, []),
    })


async def delete_template(request):
    app = request.app
    b = await request.json()
    store = load_json(STORE, {})
    store.pop(b.get("id"), None)
    save_json(STORE, store)
    render_package(store)
    await ha(app, "POST", "/services/template/reload", {})
    return web.json_response({"ok": True})


async def on_startup(app):
    app["http"] = aiohttp.ClientSession()
    render_package(load_json(STORE, {}))
    log.info("AI Builder ready - using %s", ENTITY)


async def on_cleanup(app):
    await app["http"].close()


def main():
    app = web.Application(client_max_size=4 * 1024 * 1024)
    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)
    app.add_routes([
        web.get("/", index),
        web.get("/api/status", status),
        web.get("/api/targets", targets),
        web.get("/api/mine", mine),
        web.post("/api/generate", generate),
        web.post("/api/create", create),
        web.post("/api/delete_template", delete_template),
    ])
    web.run_app(app, host="0.0.0.0", port=8099, access_log=None)


if __name__ == "__main__":
    main()
