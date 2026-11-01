#!/usr/bin/env python3
"""AI Builder - turns plain-English requests into Home Assistant config using an ai_task entity."""
import ast
import asyncio
import json
import logging
import os
import platform
import re
import shutil
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


def resolve_template_file(value):
    """Path (relative to the HA config folder) where template entities are written."""
    rel = (value or "ai_builder/package.yaml").strip().strip("/")
    if rel.startswith("config/"):
        rel = rel[len("config/"):]
    parts = [p for p in rel.split("/") if p]
    if not parts or ".." in parts or not rel.lower().endswith((".yaml", ".yml")):
        log.warning("Bad template_file %r, using ai_builder/package.yaml", value)
        rel = "ai_builder/package.yaml"
    return rel


def resolve_dir(value, default):
    """An absolute folder under /addon_configs or the HA config folder."""
    v = (value or default).strip()
    if v.startswith("/config/"):
        v = v[len("/config/"):]
    p = Path(os.path.normpath(v if v.startswith("/") else str(CONF / v)))
    allowed = (Path("/addon_configs"), CONF)
    if not any(p == a or a in p.parents for a in allowed):
        log.warning("Folder %r is not allowed, using %s", value, default)
        p = Path(default)
    return p


TEMPLATE_REL = resolve_template_file(OPTS.get("template_file"))
AD_DEFAULT = "/addon_configs/a0d7b954_appdaemon/apps"
AD_DIR = resolve_dir(OPTS.get("appdaemon_apps_dir"), AD_DEFAULT)
PY_DIR = CONF / "pyscript"
PKG_FILE = CONF / TEMPLATE_REL
PKG_DIR = PKG_FILE.parent
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
PRIORITY = {"helper": 0, "template": 1, "scene": 2, "script": 2, "pyscript": 3,
            "appdaemon": 3, "automation": 4, "blueprint": 5, "addon": 5}
EDIT_ID_KINDS = ("automation", "scene", "appdaemon", "pyscript", "addon")
TEXT_EXT = (".yaml", ".yml", ".json", ".py", ".sh", ".md", ".txt", ".html", ".js", ".css", ".cfg", ".toml", ".ini")
BACKUPS = Path("/data/backups")
HOST_ARCH = {"aarch64": "aarch64", "arm64": "aarch64", "x86_64": "amd64", "amd64": "amd64"}.get(
    platform.machine().lower(), platform.machine())
GOOD_BASE = "ghcr.io/home-assistant/base:latest"
SCHEMA_RE = re.compile(r"^(str|password|email|url|bool|int|float|port|match|list|device|ssl)(\(.*\))?\??$")
MAP_RE = re.compile(r"^(homeassistant_config|addon_config|all_addon_configs|ssl|addons|backup|share|media)(:(rw|ro))?$")
ADDONS_DIR = Path("/addons")

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
    """True if configuration.yaml includes our file directly, or includes the folder it lives in."""
    try:
        text = (CONF / "configuration.yaml").read_text()
    except Exception:
        return False
    if TEMPLATE_REL in text:
        return True
    parts = TEMPLATE_REL.split("/")
    for i in range(1, len(parts)):
        folder = "/".join(parts[:i])
        if re.search(r"!include_dir_\w+\s+['\"]?" + re.escape(folder) + r"['\"]?\s*(?:#.*)?$", text, re.M):
            return True
    return False


def add_history(entry):
    h = load_json(HIST, [])
    h.insert(0, {**entry, "time": time.strftime("%Y-%m-%d %H:%M")})
    save_json(HIST, h[:40])


def inside(base, rel):
    rel = str(rel).replace("\\", "/").lstrip("/")
    p = (base / rel).resolve()
    b = base.resolve()
    if p != b and b not in p.parents:
        raise RuntimeError(f"Unsafe path: {rel}")
    return p


def safe_write(path, content, overwrite, mode=None):
    if path.exists() and not overwrite:
        raise FileExistsError(str(path))
    if path.exists():
        BACKUPS.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, BACKUPS / f"{time.strftime('%Y%m%d-%H%M%S')}_{str(path).strip('/').replace('/', '_')}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if mode:
        path.chmod(mode)


class BPLoader(yaml.SafeLoader):
    pass


BPLoader.add_constructor("!input", lambda l, n: l.construct_scalar(n))


def addon_files(cfg):
    f = cfg.get("files") or []
    if isinstance(f, dict):
        f = [{"path": k, "content": v} for k, v in f.items()]
    out = []
    for x in f:
        if isinstance(x, dict) and x.get("path"):
            out.append((str(x["path"]).replace("\\", "/").strip().lstrip("/"), str(x.get("content", ""))))
    return out


def py_error(code, label="Python"):
    try:
        ast.parse(code)
    except SyntaxError as e:
        return f"{label} syntax error on line {e.lineno}: {e.msg}"
    return None


def validate_item(it):
    """Return (error, notes) for code-style items. Used for preview and again before writing."""
    k, cfg, notes = it["kind"], it["config"], []
    edit = bool(it.get("edit_id"))
    if k == "appdaemon":
        code = str(cfg.get("code", ""))
        if not code.strip():
            return "No code was written.", notes
        e = py_error(code)
        if e:
            return e, notes
        tree = ast.parse(code)
        classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
        if not classes:
            return "The code has no class.", notes
        if not edit:
            if not slug(cfg.get("name", "")):
                return "App needs a name.", notes
            if cfg.get("class") not in classes:
                return f"Class {cfg.get('class')!r} is not in the code (found: {', '.join(classes)}).", notes
        c = classes.get(cfg.get("class")) or next(iter(classes.values()))
        bases = [getattr(b, "attr", getattr(b, "id", "")) for b in c.bases]
        if "Hass" not in bases:
            notes.append("The class doesn't extend hass.Hass, so AppDaemon may not treat it as a Home Assistant app.")
        if "initialize" not in {n.name for n in c.body if isinstance(n, ast.FunctionDef)}:
            notes.append("The class has no initialize() method, so AppDaemon won't do anything with it.")
    elif k == "pyscript":
        code = str(cfg.get("code", ""))
        if not code.strip():
            return "No code was written.", notes
        e = py_error(code)
        if e:
            return e, notes
        if not edit and not slug(cfg.get("name", "")):
            return "Script needs a name.", notes
    elif k == "addon":
        files = addon_files(cfg)
        if not files:
            return "No files in the add-on.", notes
        if len(files) > 40 or sum(len(c) for _, c in files) > 300_000:
            return "That add-on is too big (40 files or 300 KB max).", notes
        for p, c in files:
            parts = p.split("/")
            base = parts[-1]
            if ".." in parts or not base:
                return f"Unsafe file path: {p}", notes
            if not (base == "Dockerfile" or base.lower().endswith(TEXT_EXT)):
                return f"File type not allowed: {p}", notes
            if base.endswith(".py"):
                e = py_error(c, p)
                if e:
                    return e, notes
        names = {p for p, _ in files}
        cf = next(((p, c) for p, c in files if p in ("config.yaml", "config.yml")), None)
        if cf:
            try:
                y = yaml.safe_load(cf[1])
            except yaml.YAMLError as e:
                return f"config.yaml is not valid YAML: {e}", notes
            if not isinstance(y, dict):
                return "config.yaml is not a mapping.", notes
            missing = [x for x in ("name", "version", "slug", "description") if x not in y]
            if missing:
                return "config.yaml is missing: " + ", ".join(missing), notes
            if not isinstance(y.get("version"), str):
                return "config.yaml: version must be a quoted string like \"1.0.0\".", notes
            for key, ok in (("startup", ("initialize", "system", "services", "application", "once")),
                            ("boot", ("auto", "manual", "manual_only"))):
                if key in y and y[key] not in ok:
                    return f"config.yaml: {key} must be one of {', '.join(ok)}.", notes
            opts, sch = y.get("options"), y.get("schema")
            if isinstance(opts, dict) and opts:
                if not isinstance(sch, dict):
                    return "config.yaml has options but no schema. Every option needs a schema entry.", notes
                miss = [k for k in opts if k not in sch]
                if miss:
                    return "config.yaml: these options are missing from schema: " + ", ".join(miss), notes
            if isinstance(sch, dict):
                for k, v in sch.items():
                    if isinstance(v, str) and not SCHEMA_RE.match(v):
                        return f"config.yaml: schema type {v!r} for {k} isn't valid (use str, int, float, bool, password, url, port, email, list(a|b), match(regex), add ? if optional).", notes
            if isinstance(y.get("map"), list):
                badmap = [x for x in y["map"] if not MAP_RE.match(str(x))]
                if badmap:
                    return "config.yaml: invalid map entries " + ", ".join(map(str, badmap)) + ". Valid: homeassistant_config, addon_config, all_addon_configs, ssl, addons, backup, share, media.", notes
            if isinstance(y.get("arch"), list) and HOST_ARCH not in y["arch"]:
                return f"config.yaml: arch must include {HOST_ARCH}, which is what this system runs.", notes
            dk = next((c for p, c in files if p == "Dockerfile"), "")
            if dk and not re.search(r"home-assistant/", dk) and "image" not in y:
                notes.append("The Dockerfile isn't built on a Home Assistant base image, so bashio and with-contenv won't exist.")
            if "Dockerfile" not in names and "image" not in y and not edit:
                notes.append("No Dockerfile and no image set. The add-on can't build.")
        elif not edit:
            return "The add-on has no config.yaml.", notes
    elif k == "blueprint":
        content = str(cfg.get("content", ""))
        try:
            y = yaml.load(content, Loader=BPLoader)
        except yaml.YAMLError as e:
            return f"Blueprint is not valid YAML: {e}", notes
        bp = (y or {}).get("blueprint") if isinstance(y, dict) else None
        if not isinstance(bp, dict) or not bp.get("name"):
            return "Blueprint needs a blueprint: section with a name.", notes
        if bp.get("domain") != cfg.get("domain", "automation"):
            return "The blueprint's domain doesn't match.", notes
    return None, notes


def fix_addon_files(files, edit=False):
    """Repair the known ways AI-written add-ons fail on this system. Returns (files, list of fixes). Idempotent."""
    fixes = []
    out = dict(files)

    for p in list(out):
        if p.lower() in ("build.yaml", "build.yml", "build.json"):
            del out[p]
            fixes.append("Removed build.yaml (legacy per-architecture build file that points at images that don't exist).")

    if "run.sh" in out:
        lines = out["run.sh"].split("\n")
        if not lines[0].startswith("#!/usr/bin/with-contenv bashio"):
            if lines[0].startswith("#!"):
                lines[0] = "#!/usr/bin/with-contenv bashio"
            else:
                lines.insert(0, "#!/usr/bin/with-contenv bashio")
            out["run.sh"] = "\n".join(lines)
            fixes.append("Set run.sh's first line to #!/usr/bin/with-contenv bashio so options and the Supervisor token are available.")

    if "Dockerfile" in out:
        d = orig = out["Dockerfile"]
        d = re.sub(r"ghcr\.io/home-assistant/(?:amd64|aarch64|armv7|armhf|i386|\{arch\})-base[\w.-]*(?::[\w.-]+)?", GOOD_BASE, d)
        if d != orig:
            fixes.append("Replaced a per-architecture base image with the multi-arch one (" + GOOD_BASE + "). The old one fails with 'no match for platform' on this system.")
        if "BUILD_FROM" not in d and re.search(r"^FROM\s+\S*home-assistant\S*", d, re.M):
            d = re.sub(r"^FROM\s+\S*home-assistant\S*", "ARG BUILD_FROM=" + GOOD_BASE + "\nFROM ${BUILD_FROM}", d, count=1, flags=re.M)
            fixes.append("Made the Dockerfile start from ${BUILD_FROM}.")
        d2 = re.sub(r"(pip3?\s+install)(?![^\n]*--break-system-packages)", r"\1 --break-system-packages", d)
        if d2 != d:
            d = d2
            fixes.append("Added --break-system-packages to pip install (Alpine blocks plain pip installs).")
        if "/run.sh" in d and "chmod" not in d:
            if re.search(r"^CMD", d, re.M):
                d = re.sub(r"^(CMD)", "RUN chmod a+x /run.sh\n\\1", d, count=1, flags=re.M)
            else:
                d = d.rstrip("\n") + "\nRUN chmod a+x /run.sh\n"
            fixes.append("Added RUN chmod a+x /run.sh.")
        out["Dockerfile"] = d

    cname = next((p for p in ("config.yaml", "config.yml") if p in out), None)
    if cname:
        c = orig = out[cname]
        c = re.sub(r"^version:\s*([0-9][0-9.]*)\s*$", r'version: "\1"', c, flags=re.M)
        c = re.sub(r"^(\s*-\s*)(?:config)((?::(?:rw|ro))?)\s*$", r"\1homeassistant_config\2", c, flags=re.M)
        c = re.sub(r"^(\s*-\s*)addon_configs((?::(?:rw|ro))?)\s*$", r"\1all_addon_configs\2", c, flags=re.M)
        if c != orig:
            fixes.append("Corrected config.yaml (quoted the version and/or fixed folder-map names to homeassistant_config / all_addon_configs).")
        try:
            y = yaml.safe_load(c) or {}
        except yaml.YAMLError:
            y = None
        if isinstance(y, dict):
            arch = y.get("arch")
            bad = (not isinstance(arch, list) or not arch or HOST_ARCH not in arch
                   or any(a in ("armv7", "armhf", "i386") for a in arch))
            if bad and not (edit and arch is None):
                new = "arch:\n  - aarch64\n  - amd64\n"
                if re.search(r"^arch:\s*\[.*\]\s*$", c, re.M):
                    c = re.sub(r"^arch:\s*\[.*\]\s*$", new.rstrip("\n"), c, count=1, flags=re.M)
                elif re.search(r"^arch:\s*\n(?:\s+-.*\n?)+", c, re.M):
                    c = re.sub(r"^arch:\s*\n(?:\s+-.*\n?)+", new, c, count=1, flags=re.M)
                else:
                    c = c.rstrip("\n") + "\n" + new
                fixes.append("Set arch to aarch64 and amd64 (old 32-bit architectures are gone, and your system must be listed).")
            if "run.sh" in out and y.get("init") is not False:
                if re.search(r"^init:.*$", c, re.M):
                    c = re.sub(r"^init:.*$", "init: false", c, count=1, flags=re.M)
                else:
                    c = c.rstrip("\n") + "\ninit: false\n"
                fixes.append("Added init: false (without it the add-on crashes at start with a pid 1 error).")
        out[cname] = c
    return list(out.items()), sorted(set(fixes), key=fixes.index)


def describe(it):
    c, k = it["config"], it["kind"]
    if k == "appdaemon":
        name = slug(c.get("name") or "app")
        out = []
        if not it.get("edit_id"):
            args = c.get("args") if isinstance(c.get("args"), dict) else {}
            out.append(f"# apps/ai_builder/{name}.yaml\n" + yaml.safe_dump(
                {name: {"module": name, "class": c.get("class"), **args}}, sort_keys=False, allow_unicode=True))
        out.append(f"# {it.get('edit_id') or 'apps/ai_builder/' + name + '.py'}\n" + str(c.get("code", "")))
        return "\n".join(out)
    if k == "pyscript":
        return f"# pyscript/{it.get('edit_id') or slug(c.get('name') or 'script') + '.py'}\n" + str(c.get("code", ""))
    if k == "addon":
        return "\n\n".join(f"# ===== {p} =====\n{x}" for p, x in addon_files(c))
    if k == "blueprint":
        return str(c.get("content", ""))
    return yaml.safe_dump(c, sort_keys=False, allow_unicode=True, width=100)


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
- "scene": config keys: name, optional icon, entities (object of entity_id -> state string, or -> object with state plus attributes such as brightness, color_temp, rgb_color, position). Only include entities that should change.
- "appdaemon": an AppDaemon 4 app. config keys: name (snake_case, used as the file and module name), class (CamelCase), args (object of settings passed to the app, optional), code (full Python source). Use `import appdaemon.plugins.hass.hassapi as hass`, `class X(hass.Hass)`, an `initialize(self)` method, and self.listen_state / run_daily / run_every / call_service / get_state / turn_on etc. Read settings from self.args.
- "pyscript": a pyscript file. config keys: name (snake_case), code (full Python source). Use pyscript features: @service, @state_trigger, @time_trigger, @event_trigger, state.get(), state.set(), task.sleep(), log.info(), and call services as plain functions like light.turn_on(entity_id="light.x"). No imports are needed for those.
- "blueprint": config keys: domain ("automation" or "script"), filename (snake_case), content (full blueprint YAML as a string, using !input for inputs).
- "addon": a Home Assistant add-on. config keys: slug (snake_case), files (list of {{"path": "config.yaml", "content": "..."}}). Always include config.yaml (name, version, slug, description, arch [aarch64, amd64], startup, boot, options, schema, and map/ingress/panel settings as needed), Dockerfile (ARG BUILD_FROM=ghcr.io/home-assistant/base:latest, FROM ${{BUILD_FROM}}, apk add what you need, COPY files, COPY run.sh /run.sh, RUN chmod a+x /run.sh, CMD ["/run.sh"]), run.sh (#!/usr/bin/with-contenv bashio, then exec the program), README.md, DOCS.md and CHANGELOG.md. IMPORTANT: when run.sh uses with-contenv, config.yaml MUST contain `init: false`. Options are read from /data/options.json. For a web UI use ingress: true with ingress_port, and use relative URLs in the page. Access Home Assistant with homeassistant_api: true and the SUPERVISOR_TOKEN env var against http://supervisor/core/api. No binary files.
- "answer": use when the person asked a question, the request is unclear, or it cannot be done. config: {{"text": "your answer"}}.

Rules:
- Code goes inside JSON strings, so escape newlines and quotes correctly. The JSON must parse.
- When editing existing code, return the FULL updated file (for add-ons, return every file you changed or added, in full), keep everything the person didn't ask to change, and for add-ons bump the version and add a CHANGELOG entry.
- A request can need several items (for example helpers + a template sensor + an automation). Return all of them in "items".
- Use ONLY entity_ids from the lists below. If something needed is missing, still write the config with your best guess and add a warning naming the missing entity.
- Only use real Home Assistant actions (services). Never invent any.
- Prefer built-in features over complicated templates. Keep it simple and reliable.
- Notifications: use a notify service from the list when one fits.
"""



KNOWHOW = """
VERIFIED FACTS ABOUT THIS SYSTEM (follow these exactly; they come from real failures):
Add-ons
- This system's CPU is @@ARCH@@. Never hard-code any architecture in an image name.
- The ONLY base image that works is ghcr.io/home-assistant/base:latest (multi-arch). Images named amd64-base, aarch64-base, armv7-base, or *-base-python do NOT work ("no match for platform"). Do not create build.yaml.
- Known-good Dockerfile:
  ARG BUILD_FROM=ghcr.io/home-assistant/base:latest
  FROM ${BUILD_FROM}
  RUN apk add --no-cache python3 py3-aiohttp py3-yaml
  WORKDIR /app
  COPY main.py /app/
  COPY run.sh /run.sh
  RUN chmod a+x /run.sh
  CMD [ "/run.sh" ]
- Known-good run.sh: first line #!/usr/bin/with-contenv bashio, then: exec python3 -u /app/main.py. config.yaml MUST contain init: false.
- Install Python libraries with apk when possible (py3-flask, py3-aiohttp, py3-requests, py3-yaml, py3-paho-mqtt). If pip is unavoidable, use pip install --break-system-packages.
- config.yaml: version must be a quoted string. arch is [aarch64, amd64] only. startup is one of initialize, system, services, application, once. boot is auto, manual or manual_only.
- Valid map entries only: homeassistant_config (mounted at /homeassistant), addon_config (the add-on's own folder, at /config), all_addon_configs (at /addon_configs), ssl, addons, backup, share, media. Never use "config".
- Every key in options needs a matching schema entry. Schema types: str, int, float, bool, password, url, port, email, list(a|b), match(regex); add ? for optional. Options are read from /data/options.json. Persistent data lives in /data.
- Home Assistant API from inside an add-on: needs homeassistant_api: true, then http://supervisor/core/api with header Authorization: Bearer $SUPERVISOR_TOKEN. WebSocket: ws://supervisor/core/websocket. Supervisor API needs hassio_api: true.
- Web UI: ingress: true, ingress_port: 8099, listen on 0.0.0.0, use only relative URLs in the page (no leading slash), set panel_icon and panel_title.
Home Assistant templates and code
- A state is limited to 255 characters. Put long text in an attribute.
- There is no from_yaml filter. from_json and to_json exist.
- Always use defaults in templates (| float(0), | default('')).
- pyscript can only import modules if allow_all_imports is true in its config; prefer pyscript's built-ins.
- AppDaemon callbacks look like def cb(self, entity, attribute, old, new, **kwargs).
"""


def build_prompt(text, kind, ctx, existing, target, previous, feedback, cfg):
    p = RULES.format(
        version=cfg.get("version", "recent"),
        unit=(cfg.get("unit_system") or {}).get("temperature", "unknown"),
        tz=cfg.get("time_zone", "unknown"),
    )
    if kind and kind != "auto":
        p += f"\nThe person specifically wants this built as: {kind}.\n"
    p += KNOWHOW.replace("@@ARCH@@", HOST_ARCH) + "\n" + ctx + "\n"
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
            if kind in EDIT_ID_KINDS:
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
        if it["kind"] == "addon":
            files, fixes = fix_addon_files(addon_files(it["config"]), bool(it.get("edit_id")))
            it["config"]["files"] = [{"path": p, "content": c} for p, c in files]
            it["checks"]["fixes"] = fixes
        it["yaml"] = describe(it)
        if it["kind"] not in ("addon", "blueprint"):
            it["checks"]["unknown"] = find_unknown(it["config"], known, domains, services)
        if it["kind"] in ("appdaemon", "pyscript", "addon", "blueprint"):
            err, notes = validate_item(it)
            it["checks"]["error"] = err
            it["checks"]["notes"] = notes
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
    elif kind == "scene":
        st, d = await ha(app, "GET", f"/config/scene/config/{tid}")
    elif kind == "appdaemon":
        p = inside(AD_DIR, tid)
        return {"file": tid, "code": p.read_text()}
    elif kind == "pyscript":
        return {"name": tid, "code": inside(PY_DIR, f"{tid}.py").read_text()}
    elif kind == "addon":
        base = inside(ADDONS_DIR, tid)
        files, total = [], 0
        for f in sorted(base.rglob("*")):
            if f.is_file() and (f.name == "Dockerfile" or f.suffix.lower() in TEXT_EXT) and "__pycache__" not in f.parts:
                txt = f.read_text(errors="replace")
                total += len(txt)
                if total > 150_000:
                    break
                files.append({"path": str(f.relative_to(base)), "content": txt})
        return {"slug": tid, "files": files}
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
        "template_file": TEMPLATE_REL,
        "appdaemon_dir": str(AD_DIR),
        "appdaemon_found": AD_DIR.parent.exists(),
        "pyscript_found": PY_DIR.exists(),
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
            return web.json_response({"error": f"Could not load that to edit: {e}"})

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


async def create_scene(app, it):
    cfg = it["config"]
    if not cfg.get("name") or not isinstance(cfg.get("entities"), dict) or not cfg["entities"]:
        raise RuntimeError("A scene needs a name and at least one entity")
    sid = str(it.get("edit_id") or int(time.time() * 1000))
    body = {"id": sid, "name": cfg["name"], "entities": cfg["entities"]}
    if cfg.get("icon"):
        body["icon"] = cfg["icon"]
    st, d = await ha(app, "POST", f"/config/scene/config/{sid}", body)
    if st != 200:
        raise RuntimeError(errmsg(d))
    return {"entity": f"scene.{slug(cfg['name'])}", "name": cfg["name"]}


async def create_appdaemon(app, it):
    err, _ = validate_item(it)
    if err:
        raise RuntimeError(err)
    if not AD_DIR.parent.exists():
        raise RuntimeError(f"AppDaemon folder not found at {AD_DIR}. Set appdaemon_apps_dir in this add-on's Configuration tab.")
    cfg, ow = it["config"], bool(it.get("overwrite"))
    if it.get("edit_id"):
        p = inside(AD_DIR, it["edit_id"])
        safe_write(p, str(cfg["code"]), True)
        return {"name": p.stem, "note": "AppDaemon reloads the app on its own. Check the AppDaemon log."}
    name = slug(cfg["name"])
    sub = AD_DIR / "ai_builder"
    py, yml = sub / f"{name}.py", sub / f"{name}.yaml"
    for other in AD_DIR.rglob(f"{name}.py"):
        if other != py:
            raise RuntimeError(f"A module named {name} already exists at {other}. Use a different name.")
    if (py.exists() or yml.exists()) and not ow:
        raise FileExistsError(str(py))
    args = cfg.get("args") if isinstance(cfg.get("args"), dict) else {}
    entry = {name: {"module": name, "class": cfg["class"], **{k: v for k, v in args.items() if k not in ("module", "class")}}}
    safe_write(py, str(cfg["code"]), ow)
    safe_write(yml, yaml.safe_dump(entry, sort_keys=False, allow_unicode=True), ow)
    return {"name": name, "note": f"Wrote apps/ai_builder/{name}.py and .yaml. AppDaemon picks it up automatically. Check the AppDaemon log."}


async def create_pyscript(app, it):
    err, _ = validate_item(it)
    if err:
        raise RuntimeError(err)
    if not PY_DIR.exists():
        raise RuntimeError("No /config/pyscript folder. Install the Pyscript integration first.")
    cfg = it["config"]
    name = it.get("edit_id") or slug(cfg["name"])
    safe_write(inside(PY_DIR, f"{name}.py"), str(cfg["code"]), bool(it.get("overwrite") or it.get("edit_id")))
    st, _ = await ha(app, "POST", "/services/pyscript/reload", {})
    note = f"Wrote pyscript/{name}.py." + ("" if st == 200 else " Couldn't call pyscript.reload; reload it yourself.")
    return {"name": name, "note": note}


async def create_addon(app, it):
    cfg = it["config"]
    files, _ = fix_addon_files(addon_files(cfg), bool(it.get("edit_id")))
    cfg["files"] = [{"path": p, "content": c} for p, c in files]
    err, _ = validate_item(it)
    if err:
        raise RuntimeError(err)
    folder = it.get("edit_id") or slug(cfg.get("slug") or "")
    if not folder:
        cf = next((c for p, c in files if p in ("config.yaml", "config.yml")), "")
        folder = slug((yaml.safe_load(cf) or {}).get("slug", "")) if cf else ""
    if not folder:
        raise RuntimeError("The add-on needs a slug")
    base = inside(ADDONS_DIR, folder)
    ow = bool(it.get("overwrite") or it.get("edit_id"))
    if base.exists() and not ow:
        raise FileExistsError(str(base))
    for p, c in files:
        safe_write(inside(base, p), c, True, 0o755 if p.endswith(".sh") else None)
    return {"name": folder, "note": f"Wrote /addons/{folder}. Now open the add-on store (called Apps in newer versions), use the menu, Check for updates, then find it under Local add-ons."}


async def create_blueprint(app, it):
    err, _ = validate_item(it)
    if err:
        raise RuntimeError(err)
    cfg = it["config"]
    domain = cfg.get("domain", "automation")
    fname = slug(cfg.get("filename") or "blueprint")
    safe_write(CONF / "blueprints" / domain / "ai_builder" / f"{fname}.yaml", str(cfg["content"]), bool(it.get("overwrite")))
    return {"name": fname, "note": f"Saved. Find it under Settings, Automations, Blueprints (domain: {domain})."}


async def create(request):
    app = request.app
    b = await request.json()
    it = b.get("item") or {}
    kind = it.get("kind")
    it["overwrite"] = bool(b.get("overwrite"))
    fn = {"automation": create_automation, "script": create_script, "template": create_template,
          "helper": create_helper, "scene": create_scene, "appdaemon": create_appdaemon,
          "pyscript": create_pyscript, "addon": create_addon, "blueprint": create_blueprint}.get(kind)
    if not fn:
        return web.json_response({"ok": False, "error": "Nothing to create for this item."})
    try:
        res = await fn(app, it)
    except FileExistsError as e:
        return web.json_response({"ok": False, "exists": True,
                                  "error": f"{e} already exists."})
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
        elif d == "scene" and a.get("id"):
            out.append({"kind": "scene", "id": str(a["id"]), "name": name})
    for uid, e in load_json(STORE, {}).items():
        out.append({"kind": "template", "id": uid, "name": e["name"]})
    try:
        for f in sorted(AD_DIR.rglob("*.py")):
            if "__pycache__" not in f.parts:
                rel = str(f.relative_to(AD_DIR))
                out.append({"kind": "appdaemon", "id": rel, "name": rel})
    except OSError:
        pass
    try:
        for f in sorted(PY_DIR.glob("*.py")):
            out.append({"kind": "pyscript", "id": f.stem, "name": f.name})
    except OSError:
        pass
    try:
        for d in sorted(ADDONS_DIR.iterdir()):
            if d.is_dir() and ((d / "config.yaml").exists() or (d / "config.yml").exists()):
                out.append({"kind": "addon", "id": d.name, "name": d.name})
    except OSError:
        pass
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
    log.info("AI Builder ready - using %s, template file /config/%s, AppDaemon dir %s", ENTITY, TEMPLATE_REL, AD_DIR)


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
