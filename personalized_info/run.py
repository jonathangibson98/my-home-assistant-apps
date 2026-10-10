import os, re, shutil, time, yaml
from aiohttp import web

DIR = "/homeassistant/ai_memory"
FILE = f"{DIR}/people.yaml"
SRC = f"{DIR}/memory/merged.yaml"
BAK = f"{DIR}/backups"
KEYS = ("household", "friends", "music", "other")

def slug(t):
    return re.sub(r"[^a-z0-9]+", "_", str(t).lower()).strip("_")

def flat(o):
    if isinstance(o, dict):
        return [x for v in o.values() for x in flat(v)]
    if isinstance(o, list):
        return [x for v in o for x in flat(v)]
    return [] if o is None else [str(o)]

def import_merged():
    data = {k: {} for k in KEYS}
    try:
        raw = open(SRC).read()
    except Exception:
        return data
    parts = re.split(r"^===\s*(.+?)\s*===\s*$", raw, flags=re.M)
    for i in range(1, len(parts), 2):
        name = slug(parts[i])
        block = parts[i + 1] if i + 1 < len(parts) else ""
        lines = [l for l in block.splitlines()
                 if not (l.strip().startswith("-----") and l.strip().endswith("-----"))
                 and not l.strip().startswith("Updated:")]
        try:
            c = yaml.safe_load("\n".join(lines)) or {}
        except Exception:
            c = {}
        if "favorite" in name:
            m = data["music"].setdefault("shared", {"genres": [], "artists": []})
            m["artists"] = sorted(set(m["artists"] + flat(c)), key=str.lower)
        elif name == "household_info" and isinstance(c, dict):
            data["household"].update(c)
        elif name == "friends_info" and isinstance(c, dict):
            data["friends"].update(c)
        else:
            data["other"][name] = c
    # pull any music already sitting inside a person into the music section
    for g in ("household", "friends"):
        for k, p in data[g].items():
            if isinstance(p, dict) and "music" in p:
                m = p.pop("music")
                if isinstance(m, dict):
                    data["music"][k] = {
                        "genres": flat(m.get("genres", [])),
                        "artists": flat(m.get("artists", m.get("favorite_artists", []))),
                    }
                else:
                    data["music"][k] = {"genres": [], "artists": flat(m)}
    return data

def save(d):
    os.makedirs(BAK, exist_ok=True)
    if os.path.exists(FILE):
        shutil.copy(FILE, f"{BAK}/people-{time.strftime('%Y%m%d-%H%M%S')}.yaml")
        for old in sorted(os.listdir(BAK))[:-20]:
            os.remove(f"{BAK}/{old}")
    tmp = FILE + ".tmp"
    with open(tmp, "w") as f:
        f.write("# Edited via the Household Info app. Safe to hand-edit.\n")
        yaml.dump(d, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
    os.replace(tmp, FILE)

def load():
    if os.path.exists(FILE):
        try:
            d = yaml.safe_load(open(FILE)) or {}
            for k in KEYS:
                d.setdefault(k, {})
            return d
        except Exception as e:
            print("people.yaml unreadable, re-importing:", e, flush=True)
    d = import_merged()
    save(d)
    return d

async def index(r):
    return web.FileResponse("/index.html")

async def get_data(r):
    return web.json_response(load())

async def post_data(r):
    d = await r.json()
    if not isinstance(d, dict) or not all(k in d for k in KEYS):
        return web.json_response({"ok": False}, status=400)
    save(d)
    return web.json_response({"ok": True})

app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/api/data", get_data)
app.router.add_post("/api/data", post_data)
web.run_app(app, host="0.0.0.0", port=8099)
