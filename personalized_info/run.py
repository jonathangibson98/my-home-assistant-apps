import asyncio, datetime, json, os, re, shutil, time, urllib.request
import yaml
import paho.mqtt.client as mqtt
from aiohttp import web

DIR = "/homeassistant/ai_memory"
FILE = f"{DIR}/people.yaml"          # household, friends, other
MUSIC_FILE = f"{DIR}/music.yaml"     # music lives in its own file now
PLACES_FILE = f"{DIR}/places.yaml"   # places (addresses, workplaces) live here
SRC = f"{DIR}/memory/merged.yaml"
BAK = f"{DIR}/backups"
SETTINGS_PATH = "/data/settings.json"
KEYS = ("household", "friends", "music", "other")
BASE = "personalized_info"
DEFAULTS = {"info": "Personalized Info", "music": "Personalized Music"}
ICONS = {"info": "mdi:account-group", "music": "mdi:music"}

# Each person can be linked to their entities in Home Assistant, so the info sensor also says what they're doing
# right now (where they are, asleep, at work, gaming...). Role names match the other add-ons: Sleep Tracker makes
# binary_sensor.<person>_asleep, Work Hours binary_sensor.<person>_at_work and sensor.<person>_hours, PS5 Status a
# media player, the phone app a device tracker, battery sensor and notify service.
LINK_ROLES = {
    "person": "Person", "phone": "Phone (device tracker)", "notify": "Phone notifications", "asleep": "Asleep",
    "at_work": "At work", "work_hours": "Work hours", "gaming": "Game console", "calendar": "Calendar",
    "location": "Location sensor",
}
LIVE_EVERY = 60  # seconds between live status checks (published only when something changed)

OPT = json.load(open("/data/options.json"))
CORE = [str(p).lower() for p in OPT.get("core_people", [])]
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")

def slug(t):
    return re.sub(r"[^a-z0-9]+", "_", str(t).lower()).strip("_")

# ---------- settings: names editable in UI, IDs permanent ----------
def save_settings(d):
    with open(SETTINGS_PATH, "w") as f:
        json.dump(d, f, indent=2)

def load_settings():
    data = {}
    try:
        data = json.load(open(SETTINGS_PATH))
    except Exception:
        pass
    changed = False
    for key, default in DEFAULTS.items():
        s = data.setdefault(key, {})
        if not s.get("name"):
            s["name"] = default; changed = True
        if not s.get("unique_id"):
            s["unique_id"] = f"{BASE}_{key}"; changed = True
        if not s.get("entity_id"):
            # fixed at creation; renaming later only changes the display name
            s["entity_id"] = "sensor." + slug(s["name"]); changed = True
    if changed:
        save_settings(data)
    return data

SET = load_settings()

# ---------- data files ----------
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

def write_yaml(path, data, header):
    """Write a yaml file safely, keeping the last 20 backups of that file."""
    os.makedirs(BAK, exist_ok=True)
    stem = os.path.basename(path)[:-5]  # "people" or "music"
    if os.path.exists(path):
        shutil.copy(path, f"{BAK}/{stem}-{time.strftime('%Y%m%d-%H%M%S')}.yaml")
        mine = sorted(f for f in os.listdir(BAK) if f.startswith(stem + "-"))
        for old in mine[:-5]:
            os.remove(f"{BAK}/{old}")
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(header)
        yaml.dump(data, f, sort_keys=False, allow_unicode=True, default_flow_style=False)
    os.replace(tmp, path)

def save(d):
    write_yaml(FILE, {k: d.get(k, {}) for k in ("household", "friends", "other")},
               "# Edited via the Personalized Info app. Safe to hand-edit.\n")
    write_yaml(MUSIC_FILE, d.get("music", {}),
               "# Music for the Personalized Music sensor. Safe to hand-edit.\n")
    if "places" in d:  # an older web page won't send places, so don't wipe the file
        write_yaml(PLACES_FILE, d["places"],
                   "# Places that people link to (home, work, hangouts). Safe to hand-edit.\n")

def clean_music(m):
    """Accepts the app's own layout, or the by_person layout from the first conversion."""
    if not isinstance(m, dict):
        return {}
    m = m.get("music", m)
    if isinstance(m, dict) and "by_person" in m:
        out = {"shared": {"genres": [],
                          "artists": flat(m.get("shared_favorites", {}).get("artists", []))}}
        for k, v in m["by_person"].items():
            out[k] = {"genres": [g for g in v if g != "other"] if isinstance(v, dict) else [],
                      "artists": flat(v)}
        return out
    return m if isinstance(m, dict) else {}

def fold_music(v):
    """Turn any music shape into (genres, artists)."""
    if isinstance(v, dict):
        if "artists" in v or "genres" in v or "favorite_artists" in v:
            return (flat(v.get("genres", [])),
                    flat(v.get("artists", v.get("favorite_artists", []))))
        return [g for g in v if str(g).lower() != "other"], flat(v)
    return [], flat(v)

def fold_person_music(d):
    """Pull music keys out of people and into d["music"]. True if anything moved."""
    moved = False
    for g in ("household", "friends"):
        for k, p in d[g].items():
            if not isinstance(p, dict):
                continue
            for key in ("top_artists", "music"):
                if key not in p:
                    continue
                genres, artists = fold_music(p.pop(key))
                moved = True
                prof = d["music"].get(k)
                if not isinstance(prof, dict):
                    prof = d["music"][k] = {"genres": [], "artists": []}
                for field, new in (("genres", genres), ("artists", artists)):
                    cur = flat(prof.get(field, []))
                    prof[field] = cur + [x for x in new if x not in cur]
    return moved

def load():
    d = None
    if os.path.exists(FILE):
        try:
            d = yaml.safe_load(open(FILE)) or {}
        except Exception as e:
            print("people.yaml unreadable, re-importing:", e, flush=True)
    if d is None:
        d = import_merged()
        save(d)
        return d
    migrate = False
    if os.path.exists(MUSIC_FILE):
        d.pop("music", None)  # music.yaml is the source of truth now
        try:
            music = clean_music(yaml.safe_load(open(MUSIC_FILE)) or {})
        except Exception as e:
            print("music.yaml unreadable:", e, flush=True)
            music = {}
    else:
        # first run after the update: move music out of people.yaml into music.yaml
        music = clean_music(d.pop("music", None) or {})
        migrate = True
    d["music"] = music
    for k in KEYS:
        d.setdefault(k, {})
    # places live in places.yaml
    if os.path.exists(PLACES_FILE):
        try:
            places = yaml.safe_load(open(PLACES_FILE)) or {}
        except Exception as e:
            print("places.yaml unreadable:", e, flush=True)
            places = {}
    else:
        places, migrate = {}, True
    if not isinstance(places, dict):
        places = {}
    # an old "places" section under other moves into places.yaml
    moved = False
    if "places" in d["other"]:
        legacy = d["other"].pop("places")
        moved = True
        if isinstance(legacy, dict):
            for k, v in legacy.items():
                places.setdefault(k, v)
    d["places"] = places
    # music written inside a person (top_artists / music) moves to the music file
    moved = fold_person_music(d) or moved
    if migrate or moved:
        save(d)
    return d

# ---------- Home Assistant states (for linked entities) ----------
def ha_get(path):
    req = urllib.request.Request(f"http://supervisor/core/api{path}", headers={"Authorization": f"Bearer {TOKEN}"})
    return json.load(urllib.request.urlopen(req, timeout=10))

def ha_states():
    try:
        return {s["entity_id"]: s for s in ha_get("/states")}
    except Exception as e:
        print("Could not read Home Assistant states:", e, flush=True)
        return {}

def notify_services():
    try:
        for d in ha_get("/services"):
            if d.get("domain") == "notify":
                return ["notify." + k for k in d.get("services", {})]
    except Exception:
        pass
    return []

def ago(ts):
    """'since 11:42 PM' from an ISO time."""
    try:
        t = datetime.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone()
        return t.strftime("%I:%M %p").lstrip("0")
    except Exception:
        return None

def zone_of(state, states):
    """A person's state names their zone: "home" is zone.home, any other zone shows its friendly name."""
    if not state or state in ("not_home", "unknown", "unavailable"):
        return None
    if state == "home":
        return "zone.home"
    return next((e for e, z in states.items() if e.startswith("zone.")
                 and ((z.get("attributes") or {}).get("friendly_name") == state or e == "zone." + slug(state))), None)

def zone_places(d):
    """zone entity -> place key, for places linked to a zone."""
    out = {}
    for k, pl in (d.get("places") or {}).items():
        z = str((pl or {}).get("zone") or "").strip() if isinstance(pl, dict) else ""
        if z.startswith("zone.") and z not in out:
            out[z] = k
    return out

def suggest_zone(d, key, states, name=None):
    """Best-guess zone for a place: by name, or zone.home for the place a household member calls home."""
    pl = dict((d.get("places") or {}).get(key) or {})
    if name:
        pl["name"] = name
    words = lambda t: {w for w in re.findall(r"[a-z0-9]+", str(t).lower()) if w not in ("the", "s", "of", "and")}
    want = words(pl.get("name") or key) | words(key)
    best, score = None, 0
    for e, z in states.items():
        if not e.startswith("zone."):
            continue
        have = words((z.get("attributes") or {}).get("friendly_name", "")) | words(e.split(".", 1)[1])
        sc = len(want & have)
        if sc > score:
            best, score = e, sc
    if not best and "zone.home" in states:
        for p in d["household"].values():
            if isinstance(p, dict) and isinstance(p.get("places"), dict) and p["places"].get("home") == key:
                return "zone.home"
    return best

def live_status(d, p, states):
    """What a linked person is doing right now, from their linked entities. None when nothing is linked."""
    links = p.get("links") if isinstance(p, dict) else None
    if not isinstance(links, dict) or not states:
        return None
    st = lambda role: states.get(str(links.get(role) or ""))
    out, words = {}, []
    s = st("person") or st("phone")
    if s:
        where = s["state"]
        zone = zone_of(where, states)
        where = "home" if where == "home" else "away" if where == "not_home" else \
            (states.get(zone) or {}).get("attributes", {}).get("friendly_name", where) if zone else where
        out["location"] = where
        if zone:
            out["zone"] = zone
        key = zone_places(d).get(zone) if zone else None
        place = (d.get("places") or {}).get(key) if key else None
        if place:  # a place linked to this zone: say its name, and which of their places it is
            out["place"] = place.get("name") or key
            out["place_key"] = key
            mine = [lbl for lbl, k in (p.get("places") or {}).items() if k == key] if isinstance(p.get("places"), dict) else []
            if mine:
                out["place_role"] = mine[0]
            words.append(f"at {out['place']}" + (f" ({pretty_label(mine[0])})" if mine and slug(mine[0]) != slug(out['place']) else ""))
        else:
            words.append(where)
    s = st("location")
    if s and s["state"] not in ("unknown", "unavailable", ""):
        out["location_detail"] = s["state"]
    s = st("asleep")
    if s and s["state"] in ("on", "off"):
        out["asleep"] = s["state"] == "on"
        if out["asleep"]:
            since = (s.get("attributes") or {}).get("fell_asleep") or s.get("last_changed")
            out["asleep_since"] = ago(since)
            words.append("asleep" + (f" since {out['asleep_since']}" if out["asleep_since"] else ""))
    s = st("at_work")
    if s and s["state"] in ("on", "off"):
        out["at_work"] = s["state"] == "on"
        if out["at_work"]:
            words.append("at work")
    s = st("work_hours")
    if s and s["state"] not in ("unknown", "unavailable"):
        out["work_hours"] = s["state"]
    s = st("gaming")
    if s:
        a = s.get("attributes") or {}
        if s["state"] == "playing" and a.get("media_title"):
            out["playing"] = a["media_title"]
            words.append(f"playing {a['media_title']}")
        else:
            out["console"] = s["state"]
    s = st("calendar")
    if s and s["state"] == "on":
        out["busy_with"] = (s.get("attributes") or {}).get("message")
        if out["busy_with"]:
            words.append(f"busy: {out['busy_with']}")
    phone = str(links.get("phone") or "")
    if phone.startswith("device_tracker."):
        b = states.get(f"sensor.{phone.split('.', 1)[1]}_battery_level")
        if b and b["state"] not in ("unknown", "unavailable"):
            out["phone_battery"] = b["state"]
            words.append(f"phone {b['state']}%")
    out["text"] = " · ".join(words)
    return out or None

def pretty_label(t):
    return str(t).replace("_", " ")

def suggest_links(d, key, states):
    """Find a person's entities by the names the other add-ons and the phone app use."""
    p = d["household"].get(key) or d["friends"].get(key) or {}
    links = dict(p.get("links") or {}) if isinstance(p.get("links"), dict) else {}
    name = slug(p.get("name") or key)
    person = links.get("person") or next((e for e in (f"person.{key}", f"person.{name}") if e in states), None)
    if not person:
        person = next((e for e, s in states.items() if e.startswith("person.")
                       and slug((s.get("attributes") or {}).get("friendly_name", "")) in (key, name)), None)
    found = {}
    if person:
        found["person"] = person
    ps = person.split(".", 1)[1] if person else name
    trackers = list(((states.get(person) or {}).get("attributes") or {}).get("device_trackers") or []) if person else []
    phone = links.get("phone") or next((t for t in trackers if any(x in t for x in ("iphone", "phone", "pixel", "galaxy"))), None) \
        or next((t for t in trackers if f"sensor.{t.split('.', 1)[1]}_battery_level" in states), None)
    if phone:
        found["phone"] = phone
        base = phone.split(".", 1)[1]
        svc = f"notify.mobile_app_{base}"
        if svc in notify_services():
            found["notify"] = svc
    for role, ids in (("asleep", [f"binary_sensor.{ps}_asleep", f"binary_sensor.{key}_asleep"]),
                      ("at_work", [f"binary_sensor.{ps}_at_work", f"binary_sensor.{key}_at_work"]),
                      ("work_hours", [f"sensor.{ps}_hours", f"sensor.{key}_hours"]),
                      ("calendar", [f"calendar.{ps}", f"calendar.{key}"]),
                      ("location", [f"sensor.{ps}_location", f"sensor.{key}_location"])):
        hit = next((e for e in ids if e in states), None)
        if hit:
            found[role] = hit
    consoles = [e for e in states if e.startswith("media_player.") and any(x in e for x in ("ps5", "playstation", "xbox"))]
    mine = [e for e in consoles if ps in e or key in e]
    if mine:
        found["gaming"] = mine[0]
    return {r: e for r, e in found.items() if not links.get(r)}, found

# ---------- birthdays ----------
MONTHS = {m.lower(): i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                              "September", "October", "November", "December"], 1)}

def parse_birthday(v):
    """(year or None, month, day) from 2000-01-15, 01-15, 1/15/2000, Jan 15 2000, Jan 15..."""
    t = str(v or "").strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", t) or re.match(r"^()(\d{1,2})-(\d{1,2})$", t)
    if m:
        y, mo, da = m.group(1), int(m.group(2)), int(m.group(3))
    else:
        m = re.match(r"^(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?$", t)
        if m:
            mo, da, y = int(m.group(1)), int(m.group(2)), m.group(3) or ""
            if len(y) == 2:
                y = ("19" if int(y) > 30 else "20") + y
        else:
            m = re.match(r"^([A-Za-z]+)\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?$", t)
            if not m or m.group(1).lower()[:3] not in {k[:3] for k in MONTHS}:
                return None
            mo = next(i for k, i in MONTHS.items() if k[:3] == m.group(1).lower()[:3])
            da, y = int(m.group(2)), m.group(3) or ""
    try:
        datetime.date(2000, mo, da)
    except ValueError:
        return None
    return (int(y) if y else None), mo, da

BIRTHDAY_KEYS = ("birthday", "dob", "date_of_birth", "birth_date", "birthdate")

def birthday_of(p):
    """(field name, (year, month, day)) from whichever birthday field the person uses, or (None, None)."""
    for key in BIRTHDAY_KEYS:
        if p.get(key):
            b = parse_birthday(p[key])
            if b:
                return key, b
    return None, None

def age_of(b):
    if not b or not b[0]:
        return None
    y, mo, da = b
    t = datetime.date.today()
    return t.year - y - ((t.month, t.day) < (mo, da))

# Fields that something better already covers. They're left out of the sensor (so the AI never gets a stale
# duplicate) and the page offers to remove them.
HOME_FIELDS = re.compile(r"^(home|home_?(location|address|town|city|area)|address|lives_?(in|at)?|residence)$")
WORK_FIELDS = re.compile(r"^(work_?(location|address|place|site)|workplace|works_at|job_location|office_location)$")

def linked_place(d, p, labels):
    links = p.get("places") if isinstance(p.get("places"), dict) else {}
    for label, key in links.items():
        if re.fullmatch(labels, slug(label)):
            pl = (d.get("places") or {}).get(key)
            if isinstance(pl, dict) and (str(pl.get("zone") or "").startswith("zone.") or str(pl.get("address") or "").strip()):
                return key, pl
    return None, None

def covered_fields(d, p):
    """{field: why it's covered} for one person."""
    if not isinstance(p, dict):
        return {}
    out = {}
    for rx, labels, what in ((HOME_FIELDS, r"home", "home"), (WORK_FIELDS, r"work|job|office", "work")):
        key, pl = linked_place(d, p, labels)
        if not pl:
            continue
        how = "zone" if str(pl.get("zone") or "").startswith("zone.") else "address"
        for f in p:
            if rx.match(slug(f)) and f not in out:
                out[f] = f"{pl.get('name') or key} ({what} place with a {how})"
    used, b = birthday_of(p)
    if used:
        for f in BIRTHDAY_KEYS:
            if f != used and f in p:
                out[f] = f"the {used.replace('_', ' ')} field"
        if b[0] and "age" in p:
            out["age"] = f"their {used.replace('_', ' ')} (age is worked out from it)"
    return out

def birthdays(d):
    today = datetime.date.today()
    out = []
    for g in ("household", "friends"):
        for k, p in d[g].items():
            if not isinstance(p, dict):
                continue
            _, b = birthday_of(p)
            if not b:
                continue
            y, mo, da = b
            def on(year):  # Feb 29 falls on Feb 28 in other years
                try:
                    return datetime.date(year, mo, da)
                except ValueError:
                    return datetime.date(year, 2, 28)
            nxt = on(today.year)
            if nxt < today:
                nxt = on(today.year + 1)
            item = {"key": k, "name": p.get("name", k), "group": g, "date": nxt.isoformat(),
                    "days": (nxt - today).days}
            if y:
                item["turning"] = nxt.year - y
                item["age"] = item["turning"] - (1 if nxt != today else 0)
            out.append(item)
    out.sort(key=lambda x: x["days"])
    return out

def birthdays_text(items):
    parts = []
    for b in items[:8]:
        when = "today" if b["days"] == 0 else "tomorrow" if b["days"] == 1 else f"in {b['days']} days"
        parts.append(f"{b['name']} {'turns ' + str(b['turning']) if b.get('turning') else 'has a birthday'} {when}"
                     + ("" if b["days"] < 2 else " (%s %d)" % (datetime.date.fromisoformat(b["date"]).strftime("%b"),
                                                      datetime.date.fromisoformat(b["date"]).day)))
    return ". ".join(parts) + ("." if parts else "")

# ---------- sensor content ----------
def count_facts(o):
    if isinstance(o, dict):
        return sum(count_facts(v) for v in o.values())
    if isinstance(o, list):
        return sum(count_facts(i) for i in o)
    return 1

def to_text(o, depth=0):
    lines, pad = [], "  " * depth
    if isinstance(o, dict):
        for k, v in o.items():
            label = str(k).replace("_", " ")
            if isinstance(v, dict):
                lines.append(f"{pad}{label}:")
                lines.extend(to_text(v, depth + 1))
            elif isinstance(v, list):
                lines.append(f"{pad}{label}: {', '.join(str(i) for i in v)}")
            else:
                lines.append(f"{pad}{label}: {v}")
    return lines

def people_text(people, only=None):
    blocks = []
    for key, data in people.items():
        if only and str(key).lower() not in only:
            continue
        if not isinstance(data, dict):
            continue
        header = str(data.get("name", key)).upper()
        shown = {k: v for k, v in data.items() if k not in ("entities", "now")}
        now = (data.get("now") or {}).get("text")
        blocks.append("\n".join([header] + ([f"  right now: {now}"] if now else []) + to_text(shown, 1)))
    return "\n\n".join(blocks)

def pname(d, k):
    p = d["household"].get(k) or d["friends"].get(k)
    return p.get("name", k) if isinstance(p, dict) else k

def person_music(d, k):
    v = d["music"].get(k)
    if not isinstance(v, dict):
        return None
    m = {"genres": flat(v.get("genres", [])), "artists": flat(v.get("artists", []))}
    return m if (m["genres"] or m["artists"]) else None

def prune(o):
    """Drop blank fields so unfilled template fields stay out of the sensor."""
    empty = ("", None, [], {})
    if isinstance(o, dict):
        out = {k: prune(v) for k, v in o.items()}
        return {k: v for k, v in out.items() if v not in empty}
    if isinstance(o, list):
        return [x for x in (prune(i) for i in o) if x not in empty]
    return o

def resolve_places(d, p, now=None):
    """Turn a person's place links (label: place key) into the full place info, marking the one they're at."""
    links = p.get("places")
    if not isinstance(links, dict):
        return None
    out = {}
    for label, key in links.items():
        pl = d["places"].get(key)
        out[label] = {"key": key, **prune(pl)} if isinstance(pl, dict) else {"key": key, "missing": True}
        if now and now.get("place_key") == key:
            out[label]["here_now"] = True
    return out or None

def with_extras(d, group, states=None):
    """Copy of a group (household/friends) with each person's music, full place info and what they're doing now.
    Blank fields (like an unfilled birthday) stay out."""
    out = {}
    for k, p in group.items():
        if not isinstance(p, dict):
            out[k] = p
            continue
        q = prune({f: v for f, v in p.items() if f not in covered_fields(d, p)})
        q.pop("places", None)
        _, b = birthday_of(p)
        if age_of(b) is not None:
            q["age"] = age_of(b)
        links = q.pop("links", None)
        if links:
            q["entities"] = links
        now = live_status(d, p, states or {})
        if now:
            q["now"] = now
        pl = resolve_places(d, p, now)
        if pl:
            q["places"] = pl
        m = person_music(d, k)
        if m:
            q["music"] = m
        out[k] = q
    return out

def build_info(d, states=None):
    raw_hh, raw_fr, other = d["household"], d["friends"], d["other"]
    total = count_facts({"household": prune(raw_hh), "friends": prune(raw_fr), **other})
    hh, fr = with_extras(d, raw_hh, states), with_extras(d, raw_fr, states)
    now = datetime.datetime.now()
    ts = f"{now.strftime('%m/%d/%y')} - {now.strftime('%I:%M%p').lstrip('0').lower()}"
    everyone = {}
    for k, v in hh.items():
        if isinstance(v, dict):
            everyone[k] = {"group": "household", **v}
    for k, v in fr.items():
        if isinstance(v, dict):
            everyone[k] = {"group": "friends", **v}
    music_by_person = {k: v["music"] for k, v in everyone.items() if "music" in v}
    status = {k: v["now"] for k, v in everyone.items() if v.get("now")}
    places = prune(d["places"])
    for pk, pl in places.items():
        if isinstance(pl, dict):
            here = [everyone[k].get("name", k) for k, v in status.items() if v.get("place_key") == pk]
            if here:
                pl["people_here"] = here
    bdays = birthdays(d)
    attrs = {
        "total_facts": total, "last_update": ts,
        "household_count": len(hh), "friends_count": len(fr),
        "sections": ["household", "friends"] + list(other.keys()),
        "household": hh, "friends": fr, "everyone": everyone,
        "music_by_person": music_by_person,
        "places": places,
        "places_text": "\n".join(f"{pl.get('name', pk)}" + (f" ({pl['zone']})" if pl.get("zone") else "")
                                 + (f": {', '.join(pl['people_here'])} here now" if pl.get("people_here") else "")
                                 for pk, pl in places.items() if isinstance(pl, dict)),
        "status": status,
        "status_text": "\n".join(f"{everyone[k].get('name', k)}: {v['text']}" for k, v in status.items() if v.get("text")),
        "birthdays": bdays,
        "birthdays_today": [b["name"] for b in bdays if b["days"] == 0],
        "birthdays_text": birthdays_text(bdays),
        "entities": {k: v["entities"] for k, v in everyone.items() if v.get("entities")},
        "core_text": people_text({k: v for k, v in hh.items() if k in CORE}),
        "household_text": people_text(hh),
        "friends_text": people_text(fr),
    }
    attrs.update(other)
    return f"{total} Facts, Last Update: {ts}", attrs

def build_music(d):
    people, arts, gens, lines = {}, set(), set(), []
    for k, v in d["music"].items():
        if not isinstance(v, dict):
            continue
        a = [str(x) for x in (v.get("artists") or [])]
        g = [str(x) for x in (v.get("genres") or [])]
        n = pname(d, k)
        people[k] = {"name": n, "genres": g, "artists": a}
        arts.update(a)
        gens.update(g)
        lines.append(f"{n.upper()}\n  genres: {', '.join(g)}\n  artists: {', '.join(a)}")
    artists = sorted(arts, key=str.lower)
    genres = sorted(gens, key=str.lower)
    return len(artists), {
        "people": people,
        "artists": artists, "artists_text": ", ".join(artists),
        "genres": genres, "genres_text": ", ".join(genres),
        "music_text": "\n\n".join(lines),
    }

BUILDERS = {"info": build_info, "music": build_music}
last_sent = {}

# ---------- MQTT (with REST fallback) ----------
client = None
mq_ready = False
mq_warned = False

def disc(key):
    s = SET[key]
    return {
        "name": s["name"],
        "unique_id": s["unique_id"],
        "default_entity_id": s["entity_id"],
        "state_topic": f"{BASE}/{key}/state",
        "json_attributes_topic": f"{BASE}/{key}/attributes",
        "availability_topic": f"{BASE}/status",
        "icon": ICONS[key],
    }

def rest_post(eid, state, attrs):
    body = json.dumps({"state": state, "attributes": attrs}, default=str).encode()
    req = urllib.request.Request(
        f"http://supervisor/core/api/states/{eid}", data=body, method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=10).read()

def publish_all(only_changes=False):
    try:
        d = load()
        states = ha_states() if any(isinstance(p, dict) and p.get("links") for g in ("household", "friends")
                                    for p in d[g].values()) else {}
        built = {"info": build_info(d, states), "music": build_music(d)}
    except Exception as e:
        print("Build failed:", e, flush=True)
        return
    # the live status changes often; only send when something besides the timestamp changed
    sig = json.dumps({k: (v[1] if k != "info" else {a: b for a, b in v[1].items() if a != "last_update"})
                      for k, v in built.items()}, sort_keys=True, default=str)
    if only_changes and last_sent.get("sig") == sig:
        return
    try:
        if client is not None:
            if not mq_ready:
                return  # on_connect publishes once the broker is up
            client.publish(f"{BASE}/status", "online", qos=1, retain=True)
            for k, (state, attrs) in built.items():
                client.publish(f"homeassistant/sensor/{BASE}/{k}/config",
                               json.dumps(disc(k)), qos=1, retain=True)
                client.publish(f"{BASE}/{k}/state", str(state), qos=1, retain=True)
                client.publish(f"{BASE}/{k}/attributes",
                               json.dumps(attrs, ensure_ascii=False, default=str),
                               qos=1, retain=True)
            last_sent["sig"] = sig
            print("MQTT sensors published", flush=True)
        else:
            for k, (state, attrs) in built.items():
                a = dict(attrs)
                a["friendly_name"] = SET[k]["name"]
                a["icon"] = ICONS[k]
                rest_post(SET[k]["entity_id"], state, a)
            last_sent["sig"] = sig
            print("REST sensors published (no unique ID)", flush=True)
    except Exception as e:
        print("Publish failed:", e, flush=True)

def on_connect(c, u, flags, *a):
    global mq_ready
    mq_ready = True
    print("Connected to MQTT broker", flush=True)
    c.subscribe("homeassistant/status")
    publish_all()

def on_disconnect(c, u, *a):
    global mq_ready
    mq_ready = False
    print("Disconnected from MQTT broker", flush=True)

def on_message(c, u, msg):
    if msg.payload == b"online":  # HA just restarted
        publish_all()

def start_mqtt():
    global client, mq_warned
    if client is not None:
        return
    try:
        host = (OPT.get("mqtt_host") or "").strip()
        if host:
            c = {"host": host, "port": OPT.get("mqtt_port") or 1883,
                 "username": (OPT.get("mqtt_username") or "").strip() or None,
                 "password": OPT.get("mqtt_password") or None, "ssl": False}
            print("Using external MQTT broker at", host, flush=True)
        else:
            req = urllib.request.Request(
                "http://supervisor/services/mqtt",
                headers={"Authorization": f"Bearer {TOKEN}"})
            c = json.load(urllib.request.urlopen(req, timeout=10))["data"]
        try:
            cl = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except AttributeError:
            cl = mqtt.Client()
        if c.get("username"):
            cl.username_pw_set(c["username"], c.get("password"))
        if c.get("ssl"):
            cl.tls_set()
        cl.will_set(f"{BASE}/status", "offline", qos=1, retain=True)
        cl.on_connect = on_connect
        cl.on_disconnect = on_disconnect
        cl.on_message = on_message
        cl.connect_async(c["host"], int(c.get("port", 1883)), 60)
        cl.loop_start()
        client = cl
    except Exception as e:
        if not mq_warned:
            print(f"MQTT not available ({e}), using REST fallback", flush=True)
            mq_warned = True

# ---------- web ----------
async def index(r):
    return web.FileResponse("/index.html")

async def get_data(r):
    # a hand-edited date (birthday: 2000-01-15 without quotes) loads as a date object: send it as text
    return web.json_response(load(), dumps=lambda o: json.dumps(o, default=str))

async def post_data(r):
    d = await r.json()
    if not isinstance(d, dict) or not all(k in d for k in KEYS):
        return web.json_response({"ok": False}, status=400)
    save(d)
    publish_all()
    return web.json_response({"ok": True})

async def get_entities(r):
    """Entities and notify services for the pickers, plus the link roles."""
    loop = asyncio.get_running_loop()
    states = await loop.run_in_executor(None, ha_states)
    keep = ("person.", "device_tracker.", "binary_sensor.", "sensor.", "media_player.", "calendar.", "zone.")
    ents = [{"id": e, "name": (s.get("attributes") or {}).get("friendly_name", e)} for e, s in sorted(states.items())
            if e.startswith(keep)]
    svcs = await loop.run_in_executor(None, notify_services)
    ents += [{"id": s, "name": "Notify service"} for s in svcs]
    return web.json_response({"entities": ents, "roles": LINK_ROLES})

async def get_suggest(r):
    key = r.query.get("person", "")
    loop = asyncio.get_running_loop()
    d = await loop.run_in_executor(None, load)
    if key not in d["household"] and key not in d["friends"]:
        return web.json_response({"ok": False, "error": "Save the person first."})
    states = await loop.run_in_executor(None, ha_states)
    new, found = await loop.run_in_executor(None, suggest_links, d, key, states)
    return web.json_response({"ok": True, "new": new, "found": found})

async def get_zone_suggest(r):
    key, name = r.query.get("place", ""), r.query.get("name", "")
    loop = asyncio.get_running_loop()
    d = await loop.run_in_executor(None, load)
    states = await loop.run_in_executor(None, ha_states)
    z = suggest_zone(d, key, states, name or None)  # works before the place is saved: matched by its name
    name = (states.get(z) or {}).get("attributes", {}).get("friendly_name") if z else None
    return web.json_response({"ok": True, "zone": z, "name": name})

async def get_preview(r):
    """What the info sensor says about each person right now (for the page)."""
    loop = asyncio.get_running_loop()
    d = await loop.run_in_executor(None, load)
    states = await loop.run_in_executor(None, ha_states)
    _, attrs = build_info(d, states)
    covered = {k: c for g in ("household", "friends") for k, p in d[g].items() if (c := covered_fields(d, p))}
    return web.json_response({"status": attrs["status"], "birthdays": attrs["birthdays"], "places": attrs["places"],
                              "covered": covered,
                              "birthdays_text": attrs["birthdays_text"]})

# ---------- AI help (Home Assistant AI Task) ----------
AI_ENTITY = str(OPT.get("ai_task_entity") or "").strip()

def ai_entity():
    if AI_ENTITY:
        return AI_ENTITY
    for s in ha_get("/states"):
        if s["entity_id"].startswith("ai_task."):
            return s["entity_id"]
    raise RuntimeError("No AI Task entity found. Add one (Google Gemini, OpenAI, Anthropic, Ollama) or set ai_task_entity.")

def ai_ask(prompt, name="Personalized Info"):
    body = json.dumps({"entity_id": ai_entity(), "task_name": name, "instructions": prompt}).encode()
    req = urllib.request.Request("http://supervisor/core/api/services/ai_task/generate_data?return_response", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        out = (json.load(resp).get("service_response") or {}).get("data")
    return out if isinstance(out, str) else json.dumps(out)

def ai_json(prompt):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", ai_ask(prompt).strip())
    i, j = t.find("{"), t.rfind("}")
    return json.loads(t[i:j + 1] if i >= 0 and j > i else t)

def all_field_names(d):
    seen = {}
    for g in ("household", "friends"):
        for p in (d.get(g) or {}).values():
            if isinstance(p, dict):
                for k in p:
                    seen[k] = seen.get(k, 0) + 1
    return sorted(seen, key=lambda k: -seen[k])

def ai_job(b):
    d = load()
    if isinstance(b.get("data"), dict) and all(k in b["data"] for k in ("household", "friends")):
        d = b["data"]  # what's on the page right now, saved or not
    action = b.get("action")
    group, key = b.get("group") or "household", b.get("key") or ""
    if action == "ask":
        q = str(b.get("question") or "").strip()[:1500]
        if not q:
            raise ValueError("Ask something first.")
        ctx = people_text({**(d.get("household") or {}), **(d.get("friends") or {})})
        return {"text": ai_ask("Here is what this household keeps about its people:\n\n" + ctx[:30000] +
                               "\n\nToday is " + datetime.date.today().isoformat() + ". Answer briefly and kindly, using only this info "
                               "(say so if it isn't there): " + q)}
    if action == "place_fields":
        pl = (d.get("places") or {}).get(key)
        if not isinstance(pl, dict):
            raise ValueError("That place doesn't exist (save first).")
        out = ai_json("A home-automation app keeps notes about places for an AI assistant. Suggest up to 6 useful NEW fields "
                      "for this place that it doesn't have yet (no guessing of private facts). Reply ONLY with JSON "
                      '{"fields": [{"field": "snake_case_name", "label": "Label", "kind": "text|list", "why": "one short reason"}]}.\n\n'
                      "Place: " + json.dumps(pl, default=str)[:4000])
        return {"fields": [f for f in out.get("fields", []) if isinstance(f, dict) and f.get("field") and f["field"] not in pl][:6]}
    person = (d.get(group) or {}).get(key)
    if not isinstance(person, dict):
        raise ValueError("That person doesn't exist yet (save first).")
    shown = {k: v for k, v in person.items() if k not in ("links",)}
    if action == "suggest":
        out = ai_json("A home-automation app keeps notes about people so its voice assistant and dashboards can be personal "
                      "(birthdays, nicknames, favorite teams, games, shows, routines...). Suggest up to 8 useful NEW fields for "
                      "this person that they don't have yet. Prefer field names other people already use (listed below) so "
                      "everyone matches. Don't invent values. Reply ONLY with JSON "
                      '{"fields": [{"field": "snake_case_name", "label": "Label", "kind": "text|list", "why": "one short reason"}]}.'
                      "\n\nGroup: %s\nField names others use: %s\nThis person now: %s"
                      % (group, ", ".join(all_field_names(d)[:60]), json.dumps(shown, default=str)[:6000]))
        return {"fields": [f for f in out.get("fields", []) if isinstance(f, dict) and f.get("field") and f["field"] not in person][:8]}
    if action == "notes":
        notes = str(b.get("notes") or "").strip()[:6000]
        if not notes:
            raise ValueError("Paste or type some notes first.")
        out = ai_json("Turn these notes about %s into fields for a person record. Use ONLY facts in the notes. Prefer these "
                      "existing field names when they fit: %s. Lists for several items, dates as YYYY-MM-DD (or MM-DD with no year). "
                      'Reply ONLY with JSON {"fields": {"snake_case_name": value, ...}}.\n\nNotes:\n%s\n\nWhat we already have: %s'
                      % (person.get("name", key), ", ".join(all_field_names(d)[:60]), notes, json.dumps(shown, default=str)[:4000]))
        f = out.get("fields") if isinstance(out.get("fields"), dict) else {}
        return {"fields": {re.sub(r"[^a-z0-9_]", "_", str(k).lower()): v for k, v in f.items() if k not in ("links", "music", "places")}}
    if action == "tidy":
        out = ai_json("Tidy this person record. Find fields that mean the same thing (merge them), unclear names (rename to "
                      "clear snake_case, matching names others use where possible), and empty or junk fields (remove). Never "
                      "touch links, music or places. Reply ONLY with JSON "
                      '{"rename": {"old": "new"}, "remove": ["field"], "notes": "one sentence"}.\n\n'
                      "Field names others use: %s\nRecord: %s" % (", ".join(all_field_names(d)[:60]), json.dumps(shown, default=str)[:6000]))
        ren = {k: v for k, v in (out.get("rename") or {}).items() if k in person and k not in ("links", "music", "places") and isinstance(v, str)}
        rem = [k for k in (out.get("remove") or []) if k in person and k not in ("links", "music", "places")]
        return {"rename": ren, "remove": rem, "notes": str(out.get("notes") or "")}
    if action == "gifts":
        return {"text": ai_ask("Suggest 6 gift ideas for %s based only on this info, each with a short reason. Plain list.\n\n%s"
                               % (person.get("name", key), people_text({key: person})))}
    raise ValueError("Unknown AI action")

async def post_ai(r):
    try:
        b = await r.json()
        out = await asyncio.get_running_loop().run_in_executor(None, ai_job, b)
        return web.json_response({"ok": True, **out})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})

async def get_settings(r):
    out = {k: {"name": SET[k]["name"], "entity_id": SET[k]["entity_id"],
               "unique_id": SET[k]["unique_id"]} for k in DEFAULTS}
    out["mode"] = "MQTT (has unique ID)" if client is not None else "REST (no unique ID)"
    return web.json_response(out)

async def post_settings(r):
    d = await r.json()
    for k in DEFAULTS:
        n = (d.get(k) or "").strip()
        if n:
            SET[k]["name"] = n
    save_settings(SET)
    publish_all()
    return web.json_response({"ok": True})

async def start_bg(app):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, start_mqtt)
    await loop.run_in_executor(None, publish_all)
    async def tick():
        n = 0
        while True:
            await asyncio.sleep(LIVE_EVERY)
            n += 1
            if client is None:
                await loop.run_in_executor(None, start_mqtt)
            # every minute: republish if anyone's live status changed; every 10 minutes regardless
            await loop.run_in_executor(None, publish_all, n % 10 != 0)
    _spawn(tick())

_BG_TASKS: set = set()  # keep references so background tasks are not garbage-collected mid-run


def _spawn(coro):
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task


app = web.Application()
app.router.add_get("/", index)
app.router.add_get("/api/data", get_data)
app.router.add_post("/api/data", post_data)
app.router.add_get("/api/settings", get_settings)
app.router.add_get("/api/entities", get_entities)
app.router.add_get("/api/suggest", get_suggest)
app.router.add_get("/api/preview", get_preview)
app.router.add_get("/api/zone_suggest", get_zone_suggest)
app.router.add_post("/api/settings", post_settings)
app.router.add_post("/api/ai", post_ai)
app.on_startup.append(start_bg)
web.run_app(app, host="0.0.0.0", port=8099)
