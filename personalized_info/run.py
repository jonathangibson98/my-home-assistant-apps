import asyncio, datetime, json, os, random, re, shutil, time, urllib.parse, urllib.request
import yaml
import paho.mqtt.client as mqtt
import extra_links as XL
import profile_data as PD
from aiohttp import web

DIR = "/homeassistant/ai_memory"
FILE = f"{DIR}/people.yaml"          # household, friends, other
MUSIC_FILE = f"{DIR}/music.yaml"     # music lives in its own file now
PLACES_FILE = f"{DIR}/places.yaml"   # places (addresses, workplaces) live here
PROFILES_FILE = f"{DIR}/profiles.yaml"  # the profile sections (about, work, health, vehicles...) for each person
WWW_DIR = "/homeassistant/www"
PHOTO_DIR = "/homeassistant/www/personalized_info"  # pictures of people and places; HA serves it at /local/personalized_info/
PHOTO_URL = "/local/personalized_info"
PROFILE_AI_FILE = "/data/profile_ai.json"
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
    "at_work": "At work (older sensor)", "work_hours": "Work hours (one sensor: at work, schedule, days off)", "gaming": "Game console", "calendar": "Calendar",
    "location": "Location sensor", "day_off": "Day off (older sensor)",
}
HOUSE_KEY = "house"  # the house's own entity list lives in /data/settings.json under this name
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

def adopt_legacy(d, raw):
    """Profile fields that are now a person's own fields (job, hobbies, friends...): a value an earlier version kept in
    profiles.yaml moves to the person's own field, so it is not lost. True if anything moved."""
    moved = False
    for g in ("household", "friends"):
        for k, p in d[g].items():
            data = ((raw or {}).get(k) or {}).get("data") if isinstance((raw or {}).get(k), dict) else None
            if not isinstance(p, dict) or not isinstance(data, dict):
                continue
            for sec in PD.SECTIONS:
                vals = data.get(sec["key"])
                for f in sec["fields"]:
                    keys = PD.legacy_keys(f)
                    if not keys or not isinstance(vals, dict) or PD.empty(vals.get(f["key"])):
                        continue
                    if not any(not PD.empty(p.get(x)) for x in keys):
                        v = vals[f["key"]]
                        p[keys[0]] = v if f["type"] == "tags" else str(v)
                        moved = True
                    vals.pop(f["key"], None)
    return moved

def clean_profiles(raw):
    out = {}
    for k, v in (raw.items() if isinstance(raw, dict) else []):
        if isinstance(v, dict):
            data = PD.clean_data(v.get("data"))
            flags = PD.clean_flags(v.get("flags"))
            if data or flags != PD.clean_flags({}):
                out[str(k)] = {"data": data, "flags": flags}
    return out

def save(d):
    write_yaml(FILE, {k: d.get(k, {}) for k in ("household", "friends", "other")},
               "# Edited via the Personalized Info app. Safe to hand-edit.\n")
    write_yaml(MUSIC_FILE, d.get("music", {}),
               "# Music for the Personalized Music sensor. Safe to hand-edit.\n")
    if "profiles" in d:  # an older web page won't send profiles, so don't wipe the file
        write_yaml(PROFILES_FILE, clean_profiles(d["profiles"]),
                   "# Profile sections for each person (about, work, health, vehicles...). Safe to hand-edit.\n")
    if "relationships" in d:  # an older web page won't send them, so don't wipe the file
        write_yaml(RELS_FILE, clean_rels(d["relationships"], person_keys(d)),
                   "# Who is linked to whom (dating, friends, family...). Each link belongs to both people. Safe to hand-edit.\n")
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
    try:
        raw_profiles = yaml.safe_load(open(PROFILES_FILE)) or {} if os.path.exists(PROFILES_FILE) else {}
    except Exception as e:
        print("profiles.yaml unreadable:", e, flush=True)
        raw_profiles = {}
    keys = person_keys(d)
    if os.path.exists(RELS_FILE):
        try:
            d["relationships"] = clean_rels(yaml.safe_load(open(RELS_FILE)) or [], keys)
        except Exception as e:
            print("relationships.yaml unreadable:", e, flush=True)
            d["relationships"] = []
    else:  # first run: build the links from the partner and friends fields people already have
        d["relationships"] = import_rels(d)
        migrate = True
    moved = adopt_legacy(d, raw_profiles) or moved
    d["profiles"] = clean_profiles(raw_profiles)
    # music written inside a person (top_artists / music) moves to the music file
    moved = fold_person_music(d) or moved
    auto = autofill_new(d)  # fills empty profile spots from what is saved, once per person
    if migrate or moved or auto:
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

def clock12(t):
    """'06:30' -> '6:30 AM'."""
    try:
        h, m = str(t).split(":")
        return f"{int(h) % 12 or 12}:{m} {'AM' if int(h) < 12 else 'PM'}"
    except Exception:
        return str(t or "")

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
    s = st("day_off")
    if s and s["state"] in ("on", "off"):
        a = s.get("attributes") or {}
        out["day_off"] = s["state"] == "on"
        if out["day_off"]:
            out["day_off_reason"] = a.get("reason") or ""
            words.append("off today" + (f" ({out['day_off_reason']})" if out["day_off_reason"] else ""))
        if a.get("next_date"):
            out["next_day_off"] = f"{a.get('next_name') or 'day off'} on {a['next_date']}"
    wh = st("work_hours")
    wa = (wh.get("attributes") or {}) if wh else {}
    if "clocked_in" in wa:  # the one Work Hours sensor per person has all of this in its attributes
        if "at_work" not in out:
            out["at_work"] = bool(wa["clocked_in"])
            if out["at_work"]:
                words.append("at work")
        if "day_off" not in out and "day_off_today" in wa:
            out["day_off"] = bool(wa["day_off_today"])
            if out["day_off"]:
                out["day_off_reason"] = wa.get("day_off_reason") or ""
                words.append("off today" + (f" ({out['day_off_reason']})" if out["day_off_reason"] else ""))
        if wa.get("next_day_off") and "next_day_off" not in out:
            out["next_day_off"] = f"{wa.get('next_day_off_name') or 'day off'} on {wa['next_day_off']}"
        if wa.get("has_schedule"):
            out["work_schedule"] = wa.get("schedule_text")
            sh = wa.get("scheduled_today")
            if isinstance(sh, dict) and not out.get("day_off"):
                out["scheduled_today"] = f"{clock12(sh.get('start'))} to {clock12(sh.get('end'))}"
                if not out.get("at_work"):
                    words.append(f"scheduled today {out['scheduled_today']}")
            ns = wa.get("next_shift")
            if isinstance(ns, dict):
                out["next_shift"] = f"{ns.get('weekday')} {ns.get('date')} {clock12(ns.get('start'))} to {clock12(ns.get('end'))}"
        for k in ("status", "period_hours", "week_hours", "today_hours", "week_overtime_hours", "scheduled_hours_this_week"):
            if wa.get(k) not in (None, ""):
                out["work_" + k] = wa[k]
    phone = str(links.get("phone") or "")
    if phone.startswith("device_tracker."):
        b = states.get(f"sensor.{phone.split('.', 1)[1]}_battery_level")
        if b and b["state"] not in ("unknown", "unavailable"):
            out["phone_battery"] = b["state"]
            words.append(f"phone {b['state']}%")
    if phone.startswith("device_tracker."):
        more, more_words = XL.phone_extras(phone.split(".", 1)[1], states)
        out.update(more)
        words += more_words
    extra, extra_words = XL.extra_entities(links.get("more"), states)
    if extra:
        out["extra"] = extra
        words += extra_words
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
                      ("day_off", [f"binary_sensor.{ps}_day_off", f"binary_sensor.{key}_day_off"]),
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

RELS_FILE = f"{DIR}/relationships.yaml"  # who is dating, friends, family... with whom. Neutral: nobody is the "main" person
# type -> (what it says from the first person's side, from the second's). Same words both ways means it has no direction.
# Keep in sync with RELTYPES in index.html.
REL_TYPES = {
    "dating": ("Dating", "Dating"), "engaged": ("Engaged", "Engaged"), "married": ("Married", "Married"), "exes": ("Exes", "Exes"),
    "best_friends": ("Best friends", "Best friends"), "friends": ("Friends", "Friends"), "roommates": ("Roommates", "Roommates"),
    "coworkers": ("Coworkers", "Coworkers"), "neighbors": ("Neighbors", "Neighbors"), "siblings": ("Siblings", "Siblings"),
    "cousins": ("Cousins", "Cousins"), "family": ("Family", "Family"),
    "parent_child": ("Parent of", "Child of"), "owner_pet": ("Owner of", "Pet of"), "dislikes": ("Doesn't like", "Not liked by"),
}
PARTNER_TYPES = ("dating", "engaged", "married")
FRIEND_TYPES = ("friends", "best_friends")
PARTNER_FIELDS = ("girlfriend", "boyfriend", "partner", "spouse", "wife", "husband", "fiance", "fiancee")

def clean_rels(raw, keys):
    """The relationship list with only real people, known types, no self-links and no duplicates."""
    out, seen = [], set()
    for r in (raw if isinstance(raw, list) else []):
        if not isinstance(r, dict):
            continue
        a, b, t = str(r.get("a") or ""), str(r.get("b") or ""), str(r.get("type") or "")
        if a == b or a not in keys or b not in keys or t not in REL_TYPES:
            continue
        sig = (t,) + (tuple(sorted((a, b))) if REL_TYPES[t][0] == REL_TYPES[t][1] else (a, b))
        if sig in seen:
            continue
        seen.add(sig)
        since = str(r.get("since") or "").strip()[:10]
        out.append({"a": a, "b": b, "type": t, "since": since if re.fullmatch(r"\d{4}-\d{2}-\d{2}", since) else "",
                    "note": re.sub(r"\s+", " ", str(r.get("note") or "")).strip()[:200]})
    return out

def person_keys(d):
    return {k for g in ("household", "friends") for k, p in (d.get(g) or {}).items() if isinstance(p, dict)}

def person_name(d, k):
    p = (d.get("household") or {}).get(k) or (d.get("friends") or {}).get(k) or {}
    return str(p.get("name") or k)

def rels_of(d, k):
    """[(relationship, other person's key, wording from k's side)] for one person."""
    out = []
    for r in d.get("relationships") or []:
        if k in (r["a"], r["b"]):
            first = r["a"] == k
            out.append((r, r["b"] if first else r["a"], REL_TYPES[r["type"]][0 if first else 1]))
    return out

def rel_texts(d, k):
    return [f"{label} {person_name(d, o)}" + (f" since {r['since']}" if r["since"] else "") + (f" ({r['note']})" if r["note"] else "")
            for r, o, label in rels_of(d, k)]

def rel_detail(d, k):
    return [{"with": person_name(d, o), "key": o, "type": r["type"], "label": label, "since": r["since"], "note": r["note"]}
            for r, o, label in rels_of(d, k)]

def rel_lines(d):
    return [f"{person_name(d, r['a'])} - {REL_TYPES[r['type']][0]} - {person_name(d, r['b'])}"
            + (f" since {r['since']}" if r["since"] else "") + (f" ({r['note']})" if r["note"] else "")
            for r in d.get("relationships") or []]

def _name_note(t):
    m = re.match(r"^\s*([^(]+?)\s*(?:\((.*)\))?\s*$", str(t))
    return (m.group(1).strip(), (m.group(2) or "").strip()) if m else (str(t).strip(), "")

def _since(text):
    m = re.search(r"since\s+([A-Za-z]+\.?\s+\d{1,2},?\s*\d{4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{4})", str(text))
    b = parse_birthday(m.group(1)) if m else None
    return ("%04d-%02d-%02d" % (b[0], b[1], b[2]), m) if b and b[0] else ("", None)

def import_rels(d):
    """First run only: turn what is already saved (girlfriend, friends, 'Jon and MJ's dog', 'MJ's sister') into links."""
    names = {}
    for k in person_keys(d):
        names[k.lower()] = k
        names[person_name(d, k).lower()] = k
    out = []
    def add(a, b, t, since="", note=""):
        if a and b and a != b:
            out.append({"a": a, "b": b, "type": t, "since": since, "note": note})
    for g in ("household", "friends"):
        for k, p in d[g].items():
            if not isinstance(p, dict):
                continue
            for f in PARTNER_FIELDS:
                for item in flat(p.get(f)) if p.get(f) else []:
                    nm, note = _name_note(item)
                    since, m = _since(note)
                    if m:
                        note = re.sub(r"\s*,?\s*(together\s+)?" + re.escape(m.group(0)), "", note, flags=re.I).strip(" ,;")
                    add(k, names.get(nm.lower()), {"wife": "married", "husband": "married", "fiance": "engaged", "fiancee": "engaged"}.get(f, "dating"), since, note)
            for item in flat(p.get("friends")) if p.get("friends") else []:
                nm, note = _name_note(item)
                add(k, names.get(nm.lower()), "best_friends" if "best friend" in (nm + " " + note).lower() else "friends", "", note)
            role = str(p.get("role") or p.get("relationship") or p.get("relation") or "")
            if p.get("breed") or re.search(r"\b(dog|cat|pet)\b", role, re.I):
                for nm, o in names.items():
                    if o != k and re.search(r"\b" + re.escape(nm) + r"\b", role, re.I):
                        add(o, k, "owner_pet")
            m = re.match(r"^(.+?)[\u2019']s\s+(sister|brother)\b", role.strip(), re.I)
            if m:
                add(names.get(m.group(1).strip().lower()), k, "siblings")
    return clean_rels(out, person_keys(d))

def rel_covered(d, k, p):
    """{field: why} for the old partner / friends fields once the Relationships card holds the same people."""
    out = {}
    rels = rels_of(d, k)
    if any(r["type"] in PARTNER_TYPES for r, _, _ in rels):
        for f in PARTNER_FIELDS:
            if not PD.empty(p.get(f)):
                out[f] = "the Relationships card"
    if not PD.empty(p.get("friends")):
        names = {}
        for kk in person_keys(d):
            names[kk.lower()] = kk
            names[person_name(d, kk).lower()] = kk
        linked = {o for r, o, _ in rels if r["type"] in FRIEND_TYPES}
        if all(names.get(_name_note(i)[0].lower()) in linked for i in flat(p["friends"])):
            out["friends"] = "the Relationships card"
    return out

def covered_fields(d, p):
    """{field: why it's covered} for one person."""
    if not isinstance(p, dict):
        return {}
    out = {}
    pk = next((k for g in ("household", "friends") for k, q in (d.get(g) or {}).items() if q is p), None)
    if pk:
        out.update(rel_covered(d, pk, p))
    for rx, labels, what in ((HOME_FIELDS, r"home", "home"), (WORK_FIELDS, r"work|job|office", "work")):
        key, pl = linked_place(d, p, labels)
        if not pl:
            continue
        how = "zone" if str(pl.get("zone") or "").startswith("zone.") else "address"
        for f in p:
            if rx.match(slug(f)) and f not in out:
                out[f] = f"{pl.get('name') or key} ({what} place with a {how})"
    if not PD.empty(p.get("nickname")):  # nickname_1, nickname_2... were joined into the nickname field
        for f in p:
            if re.fullmatch(r"nickname_\d+", f):
                out[f] = "their nickname field"
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

# ---------- pictures ----------
def photo_file(v):
    """Path of an uploaded picture for a stored name, or None."""
    name = os.path.basename(str(v or ""))
    path = os.path.join(PHOTO_DIR, name)
    return path if name and name == str(v) and os.path.isfile(path) else None

def photo_url(v):
    """Where Home Assistant shows the picture (an entity_picture): an uploaded file, or the link they pasted."""
    v = str(v or "").strip()
    if v.startswith(("http://", "https://", "/")):
        return v
    path = photo_file(v)
    return f"{PHOTO_URL}/{v}?v={int(os.path.getmtime(path))}" if path else ""

def photo_ui(v):
    """Same picture, as the page loads it through the add-on."""
    v = str(v or "").strip()
    if v.startswith(("http://", "https://", "/")):
        return v
    path = photo_file(v)
    return f"img/{v}?v={int(os.path.getmtime(path))}" if path else ""

def fixpic(q):
    """Turn a stored photo into an entity_picture, so a picture name never lands in the AI text."""
    if isinstance(q, dict) and "photo" in q:
        u = photo_url(q.pop("photo"))
        if u:
            q["entity_picture"] = u
    return q

def notable_view(other):
    """other.notable_people entries that have a picture: swap the stored name for a picture link."""
    out = dict(other)
    grp = other.get("notable_people")
    if isinstance(grp, dict):
        out["notable_people"] = {k: fixpic(dict(v)) if isinstance(v, dict) else v for k, v in grp.items()}
    return out

def calc_for(d, k, p):
    """Age, zodiac, birthday countdown and upcoming dates for one person."""
    _, b = birthday_of(p)
    bd = None
    if b:
        try:
            bd = datetime.date(b[0] or 2000, b[1], b[2])
        except ValueError:
            bd = datetime.date(b[0] or 2000, 2, 28)
    prof = (d.get("profiles") or {}).get(k) or {}
    out = PD.worked_out(prof.get("data") or {}, datetime.date.today(), bd)
    if b and not b[0]:  # no year: no age
        out.pop("age", None)
        out.pop("turning", None)
    return out

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
        shown = {k: v for k, v in data.items() if k not in ("entities", "now", "entity_picture")}
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
        out[label] = {"key": key, **fixpic(prune(pl))} if isinstance(pl, dict) else {"key": key, "missing": True}
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
            q["entities"] = XL.entities_view(links)
        now = live_status(d, p, states or {})
        if now:
            q["now"] = now
        pl = resolve_places(d, p, now)
        if pl:
            q["places"] = pl
        m = person_music(d, k)
        if m:
            q["music"] = m
        rt = rel_texts(d, k)
        if rt:
            q["relationships"] = rt
        fixpic(q)
        prof = (d.get("profiles") or {}).get(k) or {}
        sp = PD.sensor_profile(prof.get("data") or {}, prof.get("flags") or PD.clean_flags({}))
        if sp:
            q["profile"] = sp
        calc = calc_for(d, k, p)
        if calc.get("zodiac"):
            q["zodiac"] = calc["zodiac"]
        if calc.get("dates_next_30_days"):
            q["coming_up"] = [f"{e['label']} in {e['days_until']} days ({e['date']})" if e["days_until"] else f"{e['label']} today"
                              for e in calc["dates_next_30_days"]]
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
            fixpic(pl)
            here = [everyone[k].get("name", k) for k, v in status.items() if v.get("place_key") == pk]
            if here:
                pl["people_here"] = here
    bdays = birthdays(d)
    house_values, house_text = XL.house_summary((SET.get(HOUSE_KEY) or {}).get("items"), states or {})
    off_today = [everyone[k].get("name", k) for k, v in status.items() if v.get("day_off")]
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
        "house": house_values, "house_text": house_text,
        "off_today": off_today, "off_today_text": ", ".join(off_today),
        "core_text": people_text({k: v for k, v in hh.items() if k in CORE}),
        "household_text": people_text(hh),
        "friends_text": people_text(fr),
    }
    attrs.update(notable_view(other))
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

def load_profile_ai():
    try:
        return json.load(open(PROFILE_AI_FILE))
    except Exception:
        return {}

def build_profiles(d, states):
    """sensor.person_profile_<name> for each person (everything about them in one place), plus sensor.person_profiles."""
    out, summary, ai = {}, {}, load_profile_ai()
    for g in ("household", "friends"):
        hh = with_extras(d, d[g], states)
        for k, q in hh.items():
            p = d[g].get(k)
            if not isinstance(p, dict):
                continue
            now = q.get("now") or {}
            calc = calc_for(d, k, p)
            links = p.get("links") if isinstance(p.get("links"), dict) else {}
            person_state = (states or {}).get(str(links.get("person") or ""))
            pic = q.get("entity_picture") or ((person_state or {}).get("attributes") or {}).get("entity_picture")
            prof = (d.get("profiles") or {}).get(k) or {}
            summ = (ai.get(k) or {})
            attrs = {
                "friendly_name": f"{p.get('name', k)} Profile", "icon": "mdi:account-details",
                "name": p.get("name", k), "group": g, "person_entity": links.get("person") or "",
                "now": now, "location": now.get("location", ""), "text": now.get("text", ""),
                "age": calc.get("age"), "zodiac": calc.get("zodiac"),
                "next_birthday": calc.get("next_birthday"), "days_until_birthday": calc.get("days_until_birthday"),
                "birthday_today": calc.get("birthday_today"),
                "upcoming_dates": calc.get("upcoming_dates", []), "dates_next_30_days": calc.get("dates_next_30_days", []),
                "profile": q.get("profile", {}), "profile_complete_percent": PD.completeness(prof.get("data") or {}, p),
                "details": {f: v for f, v in q.items() if f not in ("now", "entities", "places", "music", "profile", "entity_picture", "name", "coming_up", "relationships")},
                "relationships": q.get("relationships", []), "relationship_links": rel_detail(d, k),
                "entities": q.get("entities", {}),
                "places": q.get("places", {}),
                "music": q.get("music", {}),
                "ai_summary": summ.get("summary", ""), "ai_facts": summ.get("facts", []),
                "ai_routine": summ.get("routine", ""), "ai_updated": summ.get("updated", ""),
            }
            if pic:
                attrs["entity_picture"] = pic
            attrs = {a: v for a, v in attrs.items() if v is not None}
            state = (now.get("text") or now.get("location") or p.get("name", k))
            out[f"sensor.person_profile_{k}"] = (str(state)[:255], attrs)
            summary[k] = summ.get("summary") or now.get("text") or p.get("name", k)
    out["sensor.person_profiles"] = (len(summary), {"friendly_name": "Person Profiles", "icon": "mdi:account-multiple", "profiles": summary})
    return out

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
        states = ha_states() if (any(isinstance(p, dict) and p.get("links") for g in ("household", "friends")
                                     for p in d[g].values()) or (SET.get(HOUSE_KEY) or {}).get("items")) else {}
        built = {"info": build_info(d, states), "music": build_music(d)}
        profile_sensors = build_profiles(d, states)
    except Exception as e:
        print("Build failed:", e, flush=True)
        return
    # the live status changes often; only send when something besides the timestamp changed
    sig = json.dumps({k: (v[1] if k != "info" else {a: b for a, b in v[1].items() if a != "last_update"})
                      for k, v in built.items()}, sort_keys=True, default=str) + json.dumps(profile_sensors, sort_keys=True, default=str)
    if only_changes and last_sent.get("sig") == sig:
        return
    for eid, (state, attrs) in profile_sensors.items():  # always plain REST: these have no unique id, like before
        try:
            rest_post(eid, state, attrs)
        except Exception as e:
            print("Could not publish", eid, e, flush=True)
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

# ---------- the default AI Task for all add-ons ----------
# Picked on the page (or from the select entity in Home Assistant). Published as select.default_ai_task, which the
# other add-ons read when their own ai_task_entity option is empty.
DEFAULT_AI_TOPIC = f"{BASE}/default_ai"

def default_ai():
    return str((SET.get("ai") or {}).get("default") or "")

def ai_choices():
    out = []
    try:
        for st in ha_get("/states"):
            if st["entity_id"].startswith("ai_task."):
                f = int((st.get("attributes") or {}).get("supported_features") or 0)
                out.append({"id": st["entity_id"], "name": (st.get("attributes") or {}).get("friendly_name") or st["entity_id"],
                            "images": bool(f & 4), "attachments": bool(f & 2)})
    except Exception as e:
        print("Could not list AI Task entities:", e, flush=True)
    return out

def publish_default_ai(choices=None):
    choices = ai_choices() if choices is None else choices
    cur = default_ai() or "auto"
    attrs = {"role": "default_ai_task", "ai_task_entity": default_ai() or (choices[0]["id"] if choices else ""),
             "set_in": "Personalized Info"}
    try:
        if client is not None and mq_ready:
            opts = ["auto"] + [c["id"] for c in choices]
            if cur not in opts:
                opts.append(cur)
            client.publish(f"homeassistant/select/{BASE}/default_ai_task/config", json.dumps({
                "name": "Default AI Task", "unique_id": f"{BASE}_default_ai_task", "default_entity_id": "select.default_ai_task",
                "options": opts, "state_topic": f"{DEFAULT_AI_TOPIC}/state", "command_topic": f"{DEFAULT_AI_TOPIC}/set",
                "json_attributes_topic": f"{DEFAULT_AI_TOPIC}/attributes", "availability_topic": f"{BASE}/status",
                "icon": "mdi:robot-outline", "entity_category": "config"}), qos=1, retain=True)
            client.publish(f"{DEFAULT_AI_TOPIC}/state", cur, qos=1, retain=True)
            client.publish(f"{DEFAULT_AI_TOPIC}/attributes", json.dumps(attrs), qos=1, retain=True)
        else:
            rest_post("sensor.default_ai_task", cur, dict(attrs, friendly_name="Default AI Task", icon="mdi:robot-outline"))
    except Exception as e:
        print("Could not publish the default AI Task:", e, flush=True)

def set_default_ai(eid):
    eid = str(eid or "").strip()
    if eid in ("auto", "none"):
        eid = ""
    if eid and not re.fullmatch(r"ai_task\.[a-z0-9_]+", eid):
        raise ValueError("Pick an ai_task entity")
    SET.setdefault("ai", {})["default"] = eid
    save_settings(SET)
    print("Default AI Task:", eid or "auto (first one)", flush=True)
    publish_default_ai()

def on_connect(c, u, flags, *a):
    global mq_ready
    mq_ready = True
    print("Connected to MQTT broker", flush=True)
    c.subscribe("homeassistant/status")
    c.subscribe(f"{DEFAULT_AI_TOPIC}/set")
    publish_all()
    publish_default_ai()
    for w in ("interests", "artists"):
        publish_shuffle(w)

def on_disconnect(c, u, *a):
    global mq_ready
    mq_ready = False
    print("Disconnected from MQTT broker", flush=True)

def on_message(c, u, msg):
    if msg.topic == f"{DEFAULT_AI_TOPIC}/set":
        try:
            set_default_ai(msg.payload.decode("utf-8", "replace"))
        except Exception as e:
            print("Default AI Task not changed:", e, flush=True)
        return
    if msg.payload == b"online":  # HA just restarted
        publish_all()
        publish_default_ai()

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
    # the page script for the extra-entity lists goes after the page's own script, so it can use its helpers
    html = open("/index.html", encoding="utf-8").read()
    try:
        extra = "<script>\n" + open("/extra_links.js", encoding="utf-8").read() + "\n</script>\n"
        html = html.replace("</body>", extra + "</body>", 1) if "</body>" in html else html + extra
    except OSError as e:
        print("extra_links.js missing:", e, flush=True)
    return web.Response(text=html, content_type="text/html", headers={"Cache-Control": "no-store"})

async def get_data(r):
    # a hand-edited date (birthday: 2000-01-15 without quotes) loads as a date object: send it as text
    return web.json_response(load(), dumps=lambda o: json.dumps(o, default=str))

async def post_data(r):
    d = await r.json()
    if not isinstance(d, dict) or not all(k in d for k in KEYS):
        return web.json_response({"ok": False}, status=400)
    XL.clean_all(d)
    if "relationships" in d:
        d["relationships"] = clean_rels(d["relationships"], person_keys(d))
    save(d)
    publish_all()
    return web.json_response({"ok": True})

async def get_entities(r):
    """Entities and notify services for the pickers, plus the link roles."""
    loop = asyncio.get_running_loop()
    states = await loop.run_in_executor(None, ha_states)
    skip = ("button.", "update.", "event.", "scene.", "script.", "automation.", "ai_task.", "stt.", "tts.", "conversation.",
            "number.", "text.", "image.", "notify.", "wake_word.", "assist_satellite.", "tag.", "persistent_notification.")
    ents = [{"id": e, "name": (s.get("attributes") or {}).get("friendly_name", e)} for e, s in sorted(states.items())
            if not e.startswith(skip)]
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

async def get_suggest_more(r):
    key = r.query.get("person", "")
    loop = asyncio.get_running_loop()
    d = await loop.run_in_executor(None, load)
    p = d["household"].get(key) or d["friends"].get(key)
    if p is None:
        return web.json_response({"ok": False, "error": "Save the person first."})
    states = await loop.run_in_executor(None, ha_states)
    items = await loop.run_in_executor(None, XL.suggest_more, key, p, states)
    return web.json_response({"ok": True, "items": items})

async def get_house(r):
    loop = asyncio.get_running_loop()
    states = await loop.run_in_executor(None, ha_states)
    items = XL.clean_items((SET.get(HOUSE_KEY) or {}).get("items"), XL.MAX_HOUSE)
    values, text = XL.house_summary(items, states)
    return web.json_response({"items": items, "values": values, "text": text})

async def post_house(r):
    body = await r.json()
    items = XL.clean_items(body.get("items") if isinstance(body, dict) else None, XL.MAX_HOUSE)
    SET[HOUSE_KEY] = {"items": items}
    save_settings(SET)
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, publish_all)
    states = await loop.run_in_executor(None, ha_states)
    values, text = XL.house_summary(items, states)
    return web.json_response({"items": items, "values": values, "text": text})

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
    people, ai = {}, load_profile_ai()
    for g in ("household", "friends"):
        for k, p in d[g].items():
            if not isinstance(p, dict):
                continue
            links = p.get("links") if isinstance(p.get("links"), dict) else {}
            ha_pic = (((states.get(str(links.get("person") or "")) or {}).get("attributes") or {}).get("entity_picture")) or ""
            calc = calc_for(d, k, p)
            people[k] = {"picture": photo_ui(p.get("photo")) or ha_pic,
                         "complete": PD.completeness(((d.get("profiles") or {}).get(k) or {}).get("data") or {}, p),
                         "calc": calc, "ai": ai.get(k) or {}}
    place_pics = {k: photo_ui(pl.get("photo")) for k, pl in d["places"].items() if isinstance(pl, dict)}
    grp = (d.get("other") or {}).get("notable_people")
    notable_pics = {k: photo_ui(v.get("photo")) for k, v in grp.items() if isinstance(v, dict)} if isinstance(grp, dict) else {}
    return web.json_response({"status": attrs["status"], "birthdays": attrs["birthdays"], "places": attrs["places"],
                              "covered": covered, "people": people, "place_pics": place_pics, "notable_pics": notable_pics,
                              "birthdays_text": attrs["birthdays_text"]})

async def get_schema(r):
    return web.json_response(PD.schema())

PHOTO_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}

async def post_photo(r):
    """Save a picture for a person or place. The page shrinks it first; this keeps it under 3 MB and checks the type."""
    kind, key = r.query.get("kind", ""), slug(r.query.get("key", ""))
    ext = PHOTO_TYPES.get((r.content_type or "").lower())
    if kind not in ("person", "place") or not key or not ext:
        return web.json_response({"ok": False, "error": "Send a JPEG, PNG or WebP picture."}, status=400)
    body = await r.read()
    if not body or len(body) > 3 * 1024 * 1024:
        return web.json_response({"ok": False, "error": "That picture is too big (3 MB max)."}, status=400)
    name = f"{kind}_{key}.{ext}"
    try:
        os.makedirs(PHOTO_DIR, exist_ok=True)
        for e in set(PHOTO_TYPES.values()):  # one picture per person or place
            old = os.path.join(PHOTO_DIR, f"{kind}_{key}.{e}")
            if e != ext and os.path.isfile(old):
                os.remove(old)
        with open(os.path.join(PHOTO_DIR, name), "wb") as f:
            f.write(body)
    except OSError as e:
        return web.json_response({"ok": False, "error": f"Could not save it: {e}"}, status=500)
    return web.json_response({"ok": True, "name": name, "ui": photo_ui(name)})

def list_www_images(limit=300):
    """Pictures in Home Assistant's www folder (newest first) for the picture picker. Ones this add-on saved are
    stored by file name; others by their /local/ link."""
    out, base = [], os.path.realpath(WWW_DIR)
    if not os.path.isdir(base):
        return out
    for root, dirs, files in os.walk(base):
        depth = 0 if root == base else os.path.relpath(root, base).count(os.sep) + 1
        dirs[:] = [x for x in dirs if not x.startswith(".") and x not in ("community", "hacsfiles", "node_modules") and depth < 3]
        for f in files:
            if not f.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif")):
                continue
            full = os.path.join(root, f)
            try:
                st = os.stat(full)
            except OSError:
                continue
            if st.st_size > 15 * 1024 * 1024:
                continue
            rel = os.path.relpath(full, base).replace(os.sep, "/")
            own = os.path.realpath(root) == os.path.realpath(PHOTO_DIR)
            out.append((st.st_mtime, {"name": rel, "value": f if own else "/local/" + urllib.parse.quote(rel),
                                      "url": f"img/{f}?v={int(st.st_mtime)}" if own else "/local/" + urllib.parse.quote(rel)}))
    out.sort(key=lambda x: -x[0])
    return [o[1] for o in out[:limit]]

# ---------- zone icons as pictures ----------
ICON_CACHE = "/data/icons"  # glyph paths of the icons already fetched, so they keep working offline
ICON_SOURCES = ("https://cdn.jsdelivr.net/npm/@mdi/svg@7/svg/{}.svg",
                "https://raw.githubusercontent.com/Templarian/MaterialDesign-SVG/master/svg/{}.svg")
ICON_RE = re.compile(r"^(mdi|hass):([a-z0-9]+(?:-[a-z0-9]+)*)$")

def zone_icon_name(st):
    """The icon set on a zone in Home Assistant (mdi:home, mdi:briefcase...), or a map pin when none is set."""
    ic = str(((st or {}).get("attributes") or {}).get("icon") or "").strip().lower()
    return ic if ICON_RE.match(ic) else "mdi:map-marker"

def icon_path(name):
    """The drawing path for a Material Design icon name, or None when it can't be had."""
    m = ICON_RE.match(str(name or "").strip().lower())
    if not m:
        return None
    short = m.group(2)
    cache = os.path.join(ICON_CACHE, short + ".txt")
    try:
        with open(cache) as f:
            got = f.read().strip()
        if got:
            return got
    except OSError:
        pass
    for src in ICON_SOURCES:
        try:
            with urllib.request.urlopen(src.format(short), timeout=8) as resp:
                svg = resp.read(200000).decode("utf-8", "ignore")
        except Exception:
            continue
        m2 = re.search(r'<path[^>]*\sd="([^"]+)"', svg)
        if m2:
            try:
                os.makedirs(ICON_CACHE, exist_ok=True)
                with open(cache, "w") as f:
                    f.write(m2.group(1))
            except OSError:
                pass
            return m2.group(1)
    return None

def icon_svg(name):
    """A round picture with the icon on it: shows in this page and works as an entity_picture in Home Assistant."""
    d = icon_path(name)
    if not d:
        return None
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 48 48"><circle cx="24" cy="24" r="24" fill="#334155"/>'
            f'<g transform="translate(9 9) scale(1.25)"><path d="{d}" fill="#e2e8f0"/></g></svg>')

async def get_icon(r):
    """One icon drawn as a picture, for the picker's preview."""
    svg = await asyncio.get_running_loop().run_in_executor(None, icon_svg, r.query.get("name", ""))
    if not svg:
        raise web.HTTPNotFound()
    return web.Response(text=svg, content_type="image/svg+xml", headers={"Cache-Control": "max-age=86400"})

async def post_zone_icon(r):
    """Use a zone's own icon as the picture. Saved as a file, so it works like any other uploaded picture."""
    zone = r.query.get("zone", "")
    loop = asyncio.get_running_loop()
    states = await loop.run_in_executor(None, ha_states)
    if not zone.startswith("zone.") or zone not in states:
        return web.json_response({"ok": False, "error": "That zone was not found in Home Assistant."}, status=400)
    svg = await loop.run_in_executor(None, icon_svg, zone_icon_name(states[zone]))
    if not svg:
        return web.json_response({"ok": False, "error": "Could not get that icon. The add-on needs internet the first time it uses an icon."}, status=502)
    name = f"zoneicon_{slug(zone[5:])}.svg"  # shared by everyone who picks this zone; picking again refreshes it
    try:
        os.makedirs(PHOTO_DIR, exist_ok=True)
        with open(os.path.join(PHOTO_DIR, name), "w") as f:
            f.write(svg)
    except OSError as e:
        return web.json_response({"ok": False, "error": f"Could not save it: {e}"}, status=500)
    return web.json_response({"ok": True, "name": name, "ui": photo_ui(name)})

# ---------- custom icons from the config folder ----------
CUSTOM_ICON_DIRS = {"icons": "/homeassistant/icons", "local_icons": "/homeassistant/local_icons"}  # /config/icons and /config/local_icons
ICON_EXTS = (".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif")

def custom_icon_name(src):
    """File name a custom icon gets when it is used as a picture: custom_<folder>_<name>.<ext>."""
    folder, _, rel = src.partition("/")
    stem, ext = os.path.splitext(rel)
    return f"custom_{folder}_{slug(stem)}{ext.lower()}"

def custom_icon_file(src):
    """Real path of 'icons/foo.svg' or 'local_icons/foo.svg', only when it sits inside one of the two folders."""
    folder, _, rel = str(src or "").partition("/")
    base = CUSTOM_ICON_DIRS.get(folder)
    if not base or not rel or not rel.lower().endswith(ICON_EXTS):
        return None
    full = os.path.realpath(os.path.join(base, rel))
    if not full.startswith(os.path.realpath(base) + os.sep) or not os.path.isfile(full) or os.path.getsize(full) > 3 * 1024 * 1024:
        return None
    return full

def list_custom_icons(limit=400):
    out = []
    for folder, base in CUSTOM_ICON_DIRS.items():
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            depth = 0 if root == base else os.path.relpath(root, base).count(os.sep) + 1
            dirs[:] = [x for x in dirs if not x.startswith(".") and depth < 2]
            for f in sorted(files):
                if f.lower().endswith(ICON_EXTS):
                    src = folder + "/" + os.path.relpath(os.path.join(root, f), base).replace(os.sep, "/")
                    if custom_icon_file(src):
                        out.append({"src": src, "name": os.path.splitext(f)[0], "folder": folder, "name_saved": custom_icon_name(src),
                                    "url": "api/custom_icon?f=" + urllib.parse.quote(src)})
    return out[:limit]

async def get_custom_icon(r):
    path = custom_icon_file(r.query.get("f", ""))
    if not path:
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "max-age=300", "Content-Security-Policy": "sandbox"})

async def post_custom_icon(r):
    """Use one of the custom icons as a picture: copied to the pictures folder, so it works like any other picture."""
    src = r.query.get("f", "")
    path = custom_icon_file(src)
    if not path:
        return web.json_response({"ok": False, "error": "That icon was not found."}, status=400)
    name = custom_icon_name(src)
    try:
        os.makedirs(PHOTO_DIR, exist_ok=True)
        shutil.copyfile(path, os.path.join(PHOTO_DIR, name))
    except OSError as e:
        return web.json_response({"ok": False, "error": f"Could not save it: {e}"}, status=500)
    return web.json_response({"ok": True, "name": name, "ui": photo_ui(name)})

async def get_pictures(r):
    """What the picture picker offers: Home Assistant people with a picture, zone icons, and images in the www folder."""
    loop = asyncio.get_running_loop()
    states = await loop.run_in_executor(None, ha_states)
    zones = sorted(({"id": e, "name": (s.get("attributes") or {}).get("friendly_name", e), "icon": zone_icon_name(s),
                     "url": "api/icon?name=" + urllib.parse.quote(zone_icon_name(s))}
                    for e, s in states.items() if e.startswith("zone.")), key=lambda x: x["name"].lower())
    people = sorted(({"id": e, "name": (s.get("attributes") or {}).get("friendly_name", e), "url": (s.get("attributes") or {}).get("entity_picture")}
                     for e, s in states.items() if e.startswith("person.") and (s.get("attributes") or {}).get("entity_picture")),
                    key=lambda x: x["name"].lower())
    images = await loop.run_in_executor(None, list_www_images)
    custom = await loop.run_in_executor(None, list_custom_icons)
    return web.json_response({"people": people, "zones": zones, "custom": custom, "images": images, "www_ok": os.path.isdir(WWW_DIR)})

async def get_img(r):
    path = photo_file(r.match_info["name"])
    if not path:
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"Cache-Control": "max-age=3600"})

def profile_ai_job(key):
    d = load()
    p = d["household"].get(key) or d["friends"].get(key)
    if not isinstance(p, dict):
        raise RuntimeError("Save the person first.")
    states = ha_states()
    q = with_extras(d, {key: p}, states)[key]
    calc = calc_for(d, key, p)
    text = people_text({key: q})
    prompt = ("You are building a short profile of one person from the notes and live Home Assistant data below.\n"
              f"Today is {datetime.date.today().isoformat()}.\n{text}\n\n"
              "Reply ONLY with JSON in this shape: "
              '{"summary": "1-2 sentences, max 200 characters", "facts": ["short fact", "..."], '
              '"routine": "short text about patterns you can see, or empty"}. '
              "Max 8 facts. Use only the data above. Do not invent anything.")
    r = ai_json(prompt)
    cache = load_profile_ai()
    cache[key] = {"summary": str(r.get("summary", ""))[:255], "facts": [str(f) for f in (r.get("facts") or [])][:8],
                  "routine": str(r.get("routine", ""))[:500], "updated": datetime.datetime.now().isoformat(timespec="seconds")}
    with open(PROFILE_AI_FILE, "w") as f:
        json.dump(cache, f)
    publish_all()
    return cache[key]

async def post_profile_ai(r):
    b = await r.json()
    try:
        out = await asyncio.get_running_loop().run_in_executor(None, profile_ai_job, str((b or {}).get("person", "")))
        return web.json_response({"ok": True, "ai": out})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})

# ---------- AI help (Home Assistant AI Task) ----------
AI_ENTITY = str(OPT.get("ai_task_entity") or "").strip()

def ai_entity():
    if AI_ENTITY:
        return AI_ENTITY
    if default_ai():
        return default_ai()
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

# the profile fields that are the person's own fields: canonical name -> (label, "text" or "list")
OWN_FILL = {PD.legacy_keys(f)[0]: (f["label"], "list" if f["type"] == "tags" else "text")
            for sec in PD.SECTIONS for f in sec["fields"] if f.get("legacy")}

def fill_spec():
    """The profile form as plain text for the AI: section, field, what shape the value has."""
    out = []
    for sec in PD.SECTIONS:
        fs = []
        for f in sec["fields"]:
            if f.get("legacy"):
                continue
            t = f["type"]
            how = ("list of objects with keys: " + ", ".join(f"{x['key']} ({x['type']})" for x in f["fields"]) if t == "items"
                   else "list of short strings" if t == "tags" else "YYYY-MM-DD" if t == "date" else "HH:MM, 24 hour" if t == "time"
                   else "one of: " + ", ".join(o for o in f["options"] if o) if t == "select" else "true or false" if t == "check" else "text")
            fs.append(f"    {f['key']}: {how}   ({f['label']})")
        out.append(f"  {sec['key']} ({sec['title']}):\n" + "\n".join(fs))
    return "\n".join(out)

def own_spec():
    return "\n".join(f"  {k}: {'list of short strings' if kind == 'list' else 'text'}   ({label})" for k, (label, kind) in OWN_FILL.items())

def fill_person(d, group, key, person):
    """Ask the AI to file everything saved about one person into the profile sections."""
    notes = {k: v for k, v in person.items() if k not in ("links", "places", "photo")}
    places = []
    for label, pk in (person.get("places") or {}).items() if isinstance(person.get("places"), dict) else []:
        pl = (d.get("places") or {}).get(pk) or {}
        places.append(f"{label}: {pl.get('name', pk)}" + (f", {pl['address']}" if pl.get("address") else ""))
    text = "\n".join(to_text(notes)) + ("\nplaces they use:\n  " + "\n  ".join(places) if places else "")
    if not text.strip():
        raise ValueError("Nothing is saved about them yet.")
    out = ai_json(
        "You are filing what a household knows about one person into a profile form.\n\nTHE FORM (section, then field: shape):\n"
        + fill_spec() + "\n\nTHE PERSON'S OWN FIELDS (these are shown in the form too). Set one only if the notes say it and it is not "
        "already saved under that name or a similar one; keep their wording:\n" + own_spec() + "\n\n"
        f"WHAT IS SAVED ABOUT {str(person.get('name', key)).upper()} (group: {group}):\n{text[:9000]}\n\n"
        f"Today is {datetime.date.today().isoformat()}.\n"
        "Rules: use ONLY facts in the notes and never guess or invent. Leave out fields with nothing. Dates are YYYY-MM-DD, and skip a "
        "date that has no year. Put people in their life (partner, friends, family, pets) in family.people with a relation and a short note. "
        "A together-since or anniversary date goes in dates.important with yearly true. Job, employer and workplace go in work. Hobbies, "
        "food, music, shows and other likes go in likes. Anything that fits nowhere goes in notes.notes. A pet has no job. Do not invent "
        "contact details.\n"
        'Reply ONLY with JSON: {"sections": {"section": {"field": value}}, "own_fields": {"hobbies": [..]}, '
        '"used_fields": ["the name of each saved field whose content you fully captured"]}.')
    own = {}
    for k, v in (out.get("own_fields") or {}).items() if isinstance(out.get("own_fields"), dict) else []:
        kind = (OWN_FILL.get(k) or ("", ""))[1]
        if kind == "list" and v:
            v = [str(x).strip() for x in (v if isinstance(v, list) else [v]) if str(x).strip()]
        elif kind == "text" and v:
            v = str(v).strip()
        else:
            continue
        if v:
            own[k] = v
    return {"sections": PD.clean_data(out.get("sections")), "own_fields": own,
            "used_fields": [f for f in (out.get("used_fields") or []) if isinstance(f, str) and f in person and f not in ("links", "places", "photo")]}

AUTOFILL_FILE = "/data/autofill.json"  # who has already been filled in automatically, so a field you clear stays cleared

def rule_fill(d, group, key, person):
    """Fill the profile sections from what is already saved, with no AI: names, work, address, anniversary, music.
    Same shape as fill_person's answer. Nothing is guessed."""
    sec = {}
    def put(s, f, v):
        if not PD.empty(v):
            sec.setdefault(s, {})[f] = v
    own = {}
    name = str(person.get("name") or "").strip()
    role = str(person.get("role") or person.get("relationship") or person.get("relation") or "")
    pet = bool(person.get("breed")) or bool(re.search(r"\b(dog|cat|pet|puppy|kitten)\b", role, re.I))
    if name:
        parts = name.split()
        put("about", "first_name", parts[0])
        if len(parts) > 1:
            put("about", "last_name", " ".join(parts[1:]))
    links = person.get("places") if isinstance(person.get("places"), dict) else {}
    places = d.get("places") or {}
    def pl_of(rx, need_addr=False):
        for label, pk in links.items():
            pl = places.get(pk)
            if re.fullmatch(rx, slug(label)) and isinstance(pl, dict) and (not need_addr or str(pl.get("address") or "").strip()):
                return pl
        return None
    if not pet:
        w = pl_of(r"work|workplace|job|employer|office")
        if w and str(w.get("name") or "").strip():
            put("work", "employer", str(w["name"]).strip())
        wa = pl_of(r"work|workplace|job|employer|office|work_?(location|address|place|site)|job_location|office_location", True)
        if wa:
            put("work", "work_address", str(wa["address"]).strip())
    h = pl_of(r"home|house|residence", True)
    if h:
        put("contact", "address", str(h["address"]).strip())
    # a "together since <date>" next to the partner becomes a yearly date
    for k in ("girlfriend", "boyfriend", "partner", "spouse", "wife", "husband", "fiance", "fiancee"):
        t = str(person.get(k) or "")
        m = re.search(r"since\s+([A-Za-z]+\.?\s+\d{1,2},?\s*\d{4}|\d{4}-\d{1,2}-\d{1,2}|\d{1,2}/\d{1,2}/\d{4})", t)
        b = parse_birthday(m.group(1)) if m else None
        if b and b[0]:
            who = re.split(r"\s*[(,]", t, 1)[0].strip() or "partner"
            put("dates", "important", [{"label": "Together with " + who, "date": "%04d-%02d-%02d" % (b[0], b[1], b[2]), "yearly": True}])
            break
    mus = (d.get("music") or {}).get(key)
    if isinstance(mus, dict):
        art = [str(a) for a in flat(mus.get("artists", []))][:15] or [str(g) for g in flat(mus.get("genres", []))][:15]
        put("likes", "music", art)
    # nickname_1, nickname_2... are one nickname field
    nn = [str(person[k]).strip() for k in sorted(person) if re.fullmatch(r"nickname_\d+", k) and str(person[k]).strip()]
    if nn and not any(person.get(k) for k in ("nickname", "nicknames", "nick")):
        own["nickname"] = ", ".join(nn)
    return {"sections": PD.clean_data(sec), "own_fields": own, "used_fields": []}

def autofill_new(d):
    """Run rule_fill once for each person who has not been filled yet, adding only to empty spots. True if profiles changed."""
    try:
        done = json.load(open(AUTOFILL_FILE)) if os.path.exists(AUTOFILL_FILE) else {}
    except Exception:
        done = {}
    changed = False
    profs = d.setdefault("profiles", {})
    for g in ("household", "friends"):
        for k, p in d[g].items():
            if not isinstance(p, dict) or k in done:
                continue
            done[k] = True
            r = rule_fill(d, g, k, p)
            for sk, vals in r["sections"].items():
                cur = profs.setdefault(k, {"data": {}, "flags": PD.clean_flags({})}).setdefault("data", {}).setdefault(sk, {})
                for fk, v in vals.items():
                    if PD.empty(cur.get(fk)):
                        cur[fk] = v
                        changed = True
                    elif fk == "important" and isinstance(cur[fk], list) and not any(isinstance(x, dict) and x.get("date") == v[0]["date"] for x in cur[fk]):
                        cur[fk] = cur[fk] + v
                        changed = True
            for fk, v in r["own_fields"].items():
                if PD.empty(p.get(fk)):
                    p[fk] = v
                    changed = "people"
    try:
        with open(AUTOFILL_FILE, "w") as f:
            json.dump(done, f)
    except OSError as e:
        print("Could not remember who was auto-filled:", e, flush=True)
    return changed

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
        d["relationships"] = clean_rels(d.get("relationships"), person_keys(d))
        ctx = people_text({**(d.get("household") or {}), **(d.get("friends") or {})}) + (
            "\n\nRELATIONSHIPS (each belongs to both people):\n" + "\n".join(rel_lines(d)) if d["relationships"] else "")
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
    if action == "rules":
        return rule_fill(d, group, key, person)
    if action == "fill":
        base = rule_fill(d, group, key, person)
        try:
            out = fill_person(d, group, key, person)
        except Exception as e:  # the AI is down, out of credit, or answered nonsense: keep what needs no AI
            base["ai_error"] = str(e)[:300]
            return base
        for sk, vals in base["sections"].items():
            out["sections"].setdefault(sk, {}).update({f: v for f, v in vals.items() if PD.empty(out["sections"][sk].get(f))})
        for fk, v in base["own_fields"].items():
            out["own_fields"].setdefault(fk, v)
        return out
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

async def get_ai_default(r):
    loop = asyncio.get_running_loop()
    ch = await loop.run_in_executor(None, ai_choices)
    return web.json_response({"default": default_ai(), "option": AI_ENTITY, "choices": ch,
                              "entity": "select.default_ai_task" if client is not None else "sensor.default_ai_task"})

async def post_ai_default(r):
    try:
        b = await r.json()
        await asyncio.get_running_loop().run_in_executor(None, set_default_ai, b.get("entity"))
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})
    return web.json_response({"ok": True, "default": default_ai()})

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

# ---------- shuffle sensors (were the interests_shuffle and artist_shuffle AppDaemon apps) ----------
SHUFFLE_DEFAULTS = {
    "interests": {"enabled": False, "entity_id": "sensor.random_interest", "name": "Random Interest", "every_minutes": 10,
                  "fields": ["hobbies", "interests", "games", "shows_and_movies", "favorite_teams", "sports"],
                  "wildcard_entity": "", "wildcard_percent": 15, "exclude": [], "everyone_if_nobody_home": True},
    "artists": {"enabled": False, "entity_id": "sensor.random_artist", "name": "Random Artist", "every_minutes": 15,
                "on_arrival": True, "include_shared": True, "exclude": [], "everyone_if_nobody_home": True},
    "locations_sensor": "", "home_states": ["home"],
}
SHUF = {"interests": None, "artists": None, "due": {"interests": 0, "artists": 0}, "home": None}

def shuffle_settings():
    cur = SET.get("shuffle") or {}
    out = json.loads(json.dumps(SHUFFLE_DEFAULTS))
    for k, v in cur.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k].update(v)
        else:
            out[k] = v
    return out

def people_at_home(d, states, cfg):
    """Keys of people who are home: from their linked person entity, or from a locations sensor (one attribute per person)."""
    homes = {str(x).lower() for x in cfg.get("home_states") or ["home"]}
    loc = (states.get(cfg.get("locations_sensor") or "") or {}).get("attributes") or {}
    out = set()
    for g in ("household", "friends"):
        for k, p in (d.get(g) or {}).items():
            if not isinstance(p, dict):
                continue
            st = live_status(d, p, states) or {}
            if st.get("zone") == "zone.home" or str(st.get("location") or "").lower() in homes or st.get("place_role") == "home":
                out.add(k)
            elif str(loc.get(k) or loc.get(p.get("name", "")) or "").lower() in homes:
                out.add(k)
    return out

def as_list(v):
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    if isinstance(v, str) and v.strip():
        return [x.strip() for x in re.split(r"[\n,]", v) if x.strip()]
    return []

def pick_interest(d, states, cfg, home):
    c = cfg["interests"]
    ex = {slug(x) for x in c["exclude"]}
    wild = c.get("wildcard_entity")
    if wild and random.randint(1, 100) <= int(c.get("wildcard_percent") or 0):
        opts = ((states.get(wild) or {}).get("attributes") or {}).get("options") or []
        if opts:
            return random.choice(opts), {"name": "Wildcard", "source": wild, "icon": "mdi:dice-multiple"}
    keys = [k for k in home if slug(k) not in ex] or ([k for g in ("household", "friends") for k in d.get(g, {}) if slug(k) not in ex]
                                                       if c.get("everyone_if_nobody_home") else [])
    pool = []
    for k in keys:
        p = d["household"].get(k) or d["friends"].get(k) or {}
        if not isinstance(p, dict) or slug(p.get("name", k)) in ex:
            continue
        for f in c["fields"]:
            for item in as_list(p.get(f)):
                pool.append((item, {"name": p.get("name", k), "person": k, "field": f, "icon": "mdi:star-shooting"}))
    if not pool:
        return None
    return random.choice(pool)

def pick_artist(d, cfg, home):
    c = cfg["artists"]
    ex = {slug(x) for x in c["exclude"]}
    keys = [k for k in home if slug(k) not in ex]
    if not keys and c.get("everyone_if_nobody_home"):
        keys = [k for k in d["music"] if k != "shared" and slug(k) not in ex]
    if c.get("include_shared") and "shared" in d["music"]:
        keys = keys + ["shared"]
    pool = []
    for k in keys:
        m = d["music"].get(k)
        if isinstance(m, dict):
            for a in as_list(m.get("artists")):
                pool.append((a, {"name": pname(d, k) if k != "shared" else "Everyone", "person": k, "genres": as_list(m.get("genres")), "icon": "mdi:music-note"}))
    return random.choice(pool) if pool else None

def publish_shuffle(which):
    cfg = shuffle_settings()[which]
    val = SHUF.get(which)
    if not val:
        return
    state, attrs = val
    oid = cfg["entity_id"].split(".", 1)[-1]
    try:
        if client is not None and mq_ready:
            client.publish(f"homeassistant/sensor/{BASE}/shuffle_{which}/config", json.dumps({
                "name": cfg["name"], "unique_id": f"{BASE}_shuffle_{which}", "default_entity_id": cfg["entity_id"],
                "state_topic": f"{BASE}/shuffle_{which}/state", "json_attributes_topic": f"{BASE}/shuffle_{which}/attributes",
                "availability_topic": f"{BASE}/status", "icon": attrs.get("icon") or "mdi:dice-multiple"}), qos=1, retain=True)
            client.publish(f"{BASE}/shuffle_{which}/state", str(state)[:250], qos=1, retain=True)
            client.publish(f"{BASE}/shuffle_{which}/attributes", json.dumps(attrs, ensure_ascii=False), qos=1, retain=True)
        else:
            rest_post(f"sensor.{oid}", str(state)[:250], dict(attrs, friendly_name=cfg["name"]))
    except Exception as e:
        print("Shuffle publish failed:", e, flush=True)

def shuffle(which, d=None, states=None):
    cfg = shuffle_settings()
    d = d or load()
    states = states if states is not None else ha_states()
    home = people_at_home(d, states, cfg)
    got = pick_interest(d, states, cfg, home) if which == "interests" else pick_artist(d, cfg, home)
    if got:
        SHUF[which] = got
        publish_shuffle(which)
    SHUF["due"][which] = time.time() + max(1, int(cfg[which]["every_minutes"])) * 60
    return got

def shuffle_tick():
    """Every minute: reshuffle what's due, and the artist right away when someone gets home."""
    cfg = shuffle_settings()
    if not (cfg["interests"]["enabled"] or cfg["artists"]["enabled"]):
        return
    d, states = load(), ha_states()
    home = people_at_home(d, states, cfg)
    arrived = SHUF["home"] is not None and bool(home - SHUF["home"])
    SHUF["home"] = home
    for which in ("interests", "artists"):
        if not cfg[which]["enabled"]:
            continue
        if time.time() >= SHUF["due"][which] or (which == "artists" and arrived and cfg["artists"]["on_arrival"]):
            shuffle(which, d, states)

async def get_shuffle(r):
    return web.json_response({"settings": shuffle_settings(),
                              "now": {k: ({"state": SHUF[k][0], "attributes": SHUF[k][1]} if SHUF[k] else None) for k in ("interests", "artists")},
                              "fields": all_field_names(load())[:80]})

async def post_shuffle(r):
    b = await r.json()
    cur = shuffle_settings()
    for k in ("interests", "artists"):
        if isinstance(b.get(k), dict):
            cur[k].update({kk: vv for kk, vv in b[k].items() if kk in SHUFFLE_DEFAULTS[k]})
            cur[k]["entity_id"] = "sensor." + slug(str(cur[k]["entity_id"]).split(".", 1)[-1] or k)
    for k in ("locations_sensor", "home_states"):
        if k in b:
            cur[k] = b[k]
    SET["shuffle"] = cur
    save_settings(SET)
    for k in ("interests", "artists"):
        SHUF["due"][k] = 0  # pick right away with the new settings
    await asyncio.get_running_loop().run_in_executor(None, shuffle_tick)
    return await get_shuffle(r)

async def post_shuffle_now(r):
    which = (await r.json()).get("which")
    if which not in ("interests", "artists"):
        return web.json_response({"ok": False})
    got = await asyncio.get_running_loop().run_in_executor(None, shuffle, which)
    return web.json_response({"ok": bool(got), "state": got[0] if got else None, "attributes": got[1] if got else None,
                              "error": None if got else "Nothing to pick from (check the fields and who's home)."})

async def start_bg(app):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, start_mqtt)
    await loop.run_in_executor(None, publish_all)
    if client is None:
        await loop.run_in_executor(None, publish_default_ai)
    await loop.run_in_executor(None, shuffle_tick)
    async def tick():
        n = 0
        while True:
            await asyncio.sleep(LIVE_EVERY)
            n += 1
            if client is None:
                await loop.run_in_executor(None, start_mqtt)
            # every minute: republish if anyone's live status changed; every 10 minutes regardless
            await loop.run_in_executor(None, publish_all, n % 10 != 0)
            if n % 10 == 0:
                await loop.run_in_executor(None, publish_default_ai)
            await loop.run_in_executor(None, shuffle_tick)
    _spawn(tick())

_BG_TASKS: set = set()  # keep references so background tasks are not garbage-collected mid-run


def _spawn(coro):
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task


app = web.Application(client_max_size=4 * 1024 * 1024)
app.router.add_get("/", index)
app.router.add_get("/api/data", get_data)
app.router.add_post("/api/data", post_data)
app.router.add_get("/api/settings", get_settings)
app.router.add_get("/api/entities", get_entities)
app.router.add_get("/api/suggest", get_suggest)
app.router.add_get("/api/suggest_more", get_suggest_more)
app.router.add_get("/api/house", get_house)
app.router.add_post("/api/house", post_house)
app.router.add_get("/api/preview", get_preview)
app.router.add_get("/api/schema", get_schema)
app.router.add_post("/api/photo", post_photo)
app.router.add_get("/img/{name}", get_img)
app.router.add_get("/api/pictures", get_pictures)
app.router.add_get("/api/icon", get_icon)
app.router.add_get("/api/custom_icon", get_custom_icon)
app.router.add_post("/api/custom_icon", post_custom_icon)
app.router.add_post("/api/zone_icon", post_zone_icon)
app.router.add_post("/api/profile_ai", post_profile_ai)
app.router.add_get("/api/zone_suggest", get_zone_suggest)
app.router.add_post("/api/settings", post_settings)
app.router.add_post("/api/ai", post_ai)
app.router.add_get("/api/ai_default", get_ai_default)
app.router.add_post("/api/ai_default", post_ai_default)
app.router.add_get("/api/shuffle", get_shuffle)
app.router.add_post("/api/shuffle", post_shuffle)
app.router.add_post("/api/shuffle/now", post_shuffle_now)
app.on_startup.append(start_bg)
web.run_app(app, host="0.0.0.0", port=8099)
