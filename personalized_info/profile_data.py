"""What you can set on a person, and what is worked out from it. Standard library only.

SECTIONS is the single description of the form: the web page is built from it (served at /api/schema), saved data
is cleaned against it, and the sensor / AI text is made from it. Add a field here and it shows up everywhere.

Field types: text, long, date, time, number, select, tags (a list of words), url, check,
and items (a list of rows, each with its own `fields`).
Nothing here asks for passwords, card numbers or government ID numbers, on purpose.
"""
import re
from datetime import date, datetime, timedelta

TEXT_MAX, LONG_MAX, TAG_MAX, TAGS_MAX, ROWS_MAX = 300, 4000, 80, 80, 60

BLOOD = ["", "A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def F(key, label, typ="text", hint="", **kw):
    # legacy="field": the value lives in the person's own fields (people.yaml) under that name, not in the profile data
    return {"key": key, "label": label, "type": typ, "hint": hint, **kw}


SECTIONS = [
    {"key": "about", "title": "About", "icon": "🙂", "sensor": True, "ai": True,
     "hint": "The basics. Birthday gives age, zodiac sign and a countdown to the next one.",
     "fields": [
         F("first_name", "First name"), F("last_name", "Last name"), F("nickname", "Nickname", legacy="nickname"),
         F("pronouns", "Pronouns", legacy="pronouns"), F("birthday", "Birthday", "text", "2000-01-15, or 01-15 without the year", legacy="birthday"),
         F("birthplace", "Born in"),
         F("relationship", "Who they are to you", "text", "partner, son, best friend, coworker..."),
         F("languages", "Languages", "tags"),          F("bio", "A few lines about them", "long")]},
    {"key": "contact", "title": "Contact", "icon": "📇", "sensor": False, "ai": False,
     "hint": "Off by default for the sensor and the AI (turn them on above if you want them there).",
     "fields": [
         F("phone", "Phone"), F("phone2", "Other phone"), F("email", "Email"), F("address", "Home address"),
         F("social", "Social media handles", "tags"),
         F("emergency", "Emergency contacts", "items", fields=[F("name", "Name"), F("relation", "Relation"), F("phone", "Phone")])]},
    {"key": "work", "title": "Work & school", "icon": "💼", "sensor": True, "ai": True,
     "hint": "For their hours and schedule, link the Work Hours sensor under Linked entities.",
     "fields": [
         F("employer", "Employer"), F("job_title", "Job or occupation"), F("work_address", "Work address"),
         F("work_phone", "Work phone"), F("boss", "Boss or supervisor"), F("coworkers", "Coworkers", "tags"),
         F("school", "School"), F("studying", "Grade or what they study"),
         F("work_notes", "Work notes (shifts, pay day, uniform...)", "long")]},
    {"key": "health", "title": "Health", "icon": "🩺", "sensor": False, "ai": False,
     "hint": "Private: off by default. Anything you turn on goes into a Home Assistant sensor, so think about who can see it.",
     "fields": [
         F("blood_type", "Blood type", "select", options=BLOOD), F("height", "Height"), F("weight", "Weight"),
         F("allergies", "Allergies", "tags"), F("conditions", "Conditions", "tags"),
         F("medications", "Medications", "items", fields=[F("name", "Name"), F("dose", "Dose"), F("when", "When")]),
         F("doctor", "Doctor"), F("doctor_phone", "Doctor phone"), F("dentist", "Dentist"), F("pharmacy", "Pharmacy"),
         F("insurance", "Insurance provider"), F("next_checkup", "Next checkup", "date"),
         F("health_notes", "Health notes", "long")]},
    {"key": "routine", "title": "Daily routine", "icon": "⏰", "sensor": True, "ai": True,
     "hint": "Usual patterns, so the AI can tell what is normal for them.",
     "fields": [
         F("wake_time", "Usually wakes up", "time"), F("bedtime", "Usually goes to bed", "time"),
         F("leave_time", "Usually leaves home", "time"), F("home_time", "Usually gets home", "time"),
         F("work_days", "Work days", "tags", "Monday, Tuesday..."), F("workout_days", "Workout days", "tags"),
         F("routine_notes", "Anything else about their routine", "long")]},
    {"key": "likes", "title": "Likes & preferences", "icon": "❤️", "sensor": True, "ai": True,
     "hint": "Great for gift ideas, what to cook, what to put on.",
     "fields": [
         F("favorite_foods", "Favorite foods", "tags"), F("favorite_drinks", "Favorite drinks", "tags"),
         F("coffee_order", "Coffee or drink order"), F("snacks", "Snacks", "tags"),
         F("dislikes", "Dislikes", "tags"), F("diet", "Diet or food rules", "tags"),
         F("favorite_restaurants", "Favorite restaurants", "tags"), F("favorite_stores", "Favorite stores", "tags"),
         F("music", "Music and artists", "tags"), F("movies", "Movies", "tags"), F("shows", "Shows", "tags"),
         F("games", "Games", "tags", legacy="games"), F("hobbies", "Hobbies", "tags"), F("sports_teams", "Sports teams", "tags", legacy="favorite_teams"),
         F("favorite_colors", "Favorite colors", "tags"), F("scents", "Scents", "tags")]},
    {"key": "sizes", "title": "Sizes & gifts", "icon": "🎁", "sensor": True, "ai": True,
     "hint": "So you never have to guess.",
     "fields": [
         F("shirt", "Shirt size"), F("pants", "Pants size"), F("shoes", "Shoe size"), F("ring", "Ring size"),
         F("hat", "Hat size"), F("gift_ideas", "Gift ideas", "tags"),
         F("wishlist", "Wish list", "items", fields=[F("item", "Item"), F("link", "Link", "url"), F("got_it", "Got it", "check")])]},
    {"key": "vehicles", "title": "Vehicles", "icon": "🚗", "sensor": True, "ai": True,
     "hint": "Due dates show up as countdowns.",
     "fields": [
         F("cars", "Their vehicles", "items", fields=[
             F("nickname", "Nickname"), F("year", "Year"), F("make", "Make"), F("model", "Model"), F("color", "Color"),
             F("plate", "Plate"), F("registration_due", "Registration due", "date"), F("insurance_due", "Insurance due", "date"),
             F("service_due", "Next service", "date"), F("entity", "Home Assistant entity (optional)")])]},
    {"key": "dates", "title": "Important dates", "icon": "📅", "sensor": True, "ai": True,
     "hint": "Anniversaries, a started-the-job date, a memorial. Tick Every year for ones that repeat.",
     "fields": [
         F("important", "Dates", "items", fields=[F("label", "What"), F("date", "Date", "date"), F("yearly", "Every year", "check")])]},
    {"key": "family", "title": "Family, friends & pets", "icon": "👨‍👩‍👧", "sensor": True, "ai": True,
     "hint": "The people and pets in their life.",
     "fields": [
         F("people", "People and pets", "items", fields=[
             F("name", "Name"), F("relation", "Relation (mom, dog, best friend...)"), F("birthday", "Birthday", "date"), F("notes", "Notes")])]},
    {"key": "subscriptions", "title": "Memberships & subscriptions", "icon": "🔁", "sensor": False, "ai": False,
     "hint": "Renewal dates become countdowns. Never put passwords here.",
     "fields": [
         F("subs", "Memberships and subscriptions", "items", fields=[
             F("name", "Name"), F("cost", "Cost"), F("renews", "Renews on", "date"), F("notes", "Notes")])]},
    {"key": "notes", "title": "Notes & custom fields", "icon": "📝", "sensor": True, "ai": True,
     "hint": "Anything that does not fit above.",
     "fields": [
         F("notes", "Notes", "long"), F("remember", "Things to remember", "long"),
         F("custom", "Your own fields", "items", fields=[F("label", "Label"), F("value", "Value")])]},
]
SECTION = {s["key"]: s for s in SECTIONS}


def _s(v, n):
    return re.sub(r"\s+", " ", str(v if v is not None else "")).strip()[:n]


def _date(v):
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except (TypeError, ValueError):
        return ""


def _time(v):
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", str(v or "").strip())
    return "%02d:%s" % (int(m.group(1)), m.group(2)) if m else ""


def clean_value(f, v):
    t = f["type"]
    if t in ("text", "url"):
        return _s(v, TEXT_MAX)
    if t == "long":
        return str(v or "").replace("\r", "").strip()[:LONG_MAX]
    if t == "date":
        return _date(v)
    if t == "time":
        return _time(v)
    if t == "number":
        try:
            n = float(v)
            return int(n) if n == int(n) else round(n, 3)
        except (TypeError, ValueError):
            return ""
    if t == "select":
        return v if v in f.get("options", []) else ""
    if t == "check":
        return bool(v)
    if t == "tags":
        raw = v if isinstance(v, list) else re.split(r"[,\n]", str(v or ""))
        out = []
        for x in raw:
            x = _s(x, TAG_MAX)
            if x and x.lower() not in [o.lower() for o in out]:
                out.append(x)
        return out[:TAGS_MAX]
    if t == "items":
        rows = []
        for r in (v if isinstance(v, list) else [])[:ROWS_MAX]:
            if not isinstance(r, dict):
                continue
            row = {sf["key"]: clean_value(sf, r.get(sf["key"])) for sf in f["fields"]}
            if any(x not in ("", False, [], None) for x in row.values()):
                rows.append(row)
        return rows
    return ""


def empty(v):
    return v in ("", None, [], {}, False)


def clean_data(raw):
    """{section: {field: value}} with only known sections and fields, and only values that are filled in."""
    out = {}
    raw = raw if isinstance(raw, dict) else {}
    for sec in SECTIONS:
        src = raw.get(sec["key"])
        if not isinstance(src, dict):
            continue
        vals = {}
        for f in sec["fields"]:
            if f.get("legacy"):
                continue
            if f["key"] in src:
                v = clean_value(f, src[f["key"]])
                if not empty(v):
                    vals[f["key"]] = v
        if vals:
            out[sec["key"]] = vals
    return out


def clean_flags(raw):
    """Which sections go to the sensor and to the AI. Unset ones use the section's default."""
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for sec in SECTIONS:
        r = raw.get(sec["key"]) if isinstance(raw.get(sec["key"]), dict) else {}
        out[sec["key"]] = {"sensor": bool(r["sensor"]) if "sensor" in r else sec["sensor"],
                           "ai": bool(r["ai"]) if "ai" in r else sec["ai"]}
    return out


def clean_links(raw):
    out, seen = [], set()
    for it in (raw if isinstance(raw, list) else [])[:80]:
        eid = str((it.get("entity_id") if isinstance(it, dict) else it) or "").strip().lower()
        if re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", eid) and eid not in seen:
            seen.add(eid)
            out.append({"entity_id": eid, "label": _s(it.get("label"), 60) if isinstance(it, dict) else ""})
    return out


def clean_ids(raw):
    return sorted({str(x).strip().lower() for x in (raw if isinstance(raw, list) else [])
                   if re.fullmatch(r"[a-z0-9_]+\.[a-z0-9_]+", str(x).strip().lower())})[:400]


# ---------- worked out from what was set ----------
ZODIAC = [(1, 20, "Capricorn"), (2, 19, "Aquarius"), (3, 20, "Pisces"), (4, 20, "Aries"), (5, 21, "Taurus"),
          (6, 21, "Gemini"), (7, 23, "Cancer"), (8, 23, "Leo"), (9, 23, "Virgo"), (10, 23, "Libra"),
          (11, 22, "Scorpio"), (12, 22, "Sagittarius"), (12, 32, "Capricorn")]


def zodiac(d):
    for m, day, name in ZODIAC:
        if (d.month, d.day) < (m, day):
            return name
    return "Capricorn"


def _on_year(d, y):
    try:
        return d.replace(year=y)
    except ValueError:
        return d.replace(year=y, day=28)


def next_on(d, today, yearly=True):
    """The next date on or after today for a date that may repeat every year."""
    if not yearly:
        return d if d >= today else None
    n = _on_year(d, today.year)
    return n if n >= today else _on_year(d, today.year + 1)


def countdown(label, d, today, yearly=True, extra=None):
    n = next_on(d, today, yearly)
    if not n:
        return None
    out = {"label": label, "date": n.isoformat(), "days_until": (n - today).days}
    if yearly and d.year < today.year + 1:
        out["turning"] = n.year - d.year
    if extra:
        out.update(extra)
    return out


def worked_out(data, today, birthday=None):
    """Age, zodiac, birthday countdown and every upcoming date. `birthday` is a datetime.date (or None) from the
    person's own birthday field, which the rest of the add-on already uses."""
    out = {}
    bd = birthday
    if bd:
        age = today.year - bd.year - ((today.month, today.day) < (bd.month, bd.day))
        nb = countdown("Birthday", bd, today)
        out.update({"age": age, "zodiac": zodiac(bd), "next_birthday": nb["date"], "days_until_birthday": nb["days_until"],
                    "birthday_today": nb["days_until"] == 0, "turning": nb.get("turning")})
    events = []
    for r in data.get("dates", {}).get("important", []):
        d = _d(r.get("date"))
        if d:
            c = countdown(r.get("label") or "Date", d, today, bool(r.get("yearly")))
            if c:
                events.append(c)
    for r in data.get("family", {}).get("people", []):
        d = _d(r.get("birthday"))
        if d:
            c = countdown("%s's birthday" % r.get("name", "Someone"), d, today)
            if c:
                events.append(c)
    for r in data.get("vehicles", {}).get("cars", []):
        nm = r.get("nickname") or ("%s %s" % (r.get("make", ""), r.get("model", ""))).strip() or "Vehicle"
        for k, lab in (("registration_due", "registration due"), ("insurance_due", "insurance due"), ("service_due", "service due")):
            d = _d(r.get(k))
            if d:
                c = countdown("%s %s" % (nm, lab), d, today, False)
                if c:
                    events.append(c)
    for r in data.get("subscriptions", {}).get("subs", []):
        d = _d(r.get("renews"))
        if d:
            c = countdown("%s renews" % (r.get("name") or "Subscription"), d, today, False)
            if c:
                events.append(c)
    d = _d(data.get("health", {}).get("next_checkup"))
    if d:
        c = countdown("Checkup", d, today, False)
        if c:
            events.append(c)
    events.sort(key=lambda e: e["days_until"])
    out["upcoming_dates"] = events[:15]
    out["dates_next_30_days"] = [e for e in events if e["days_until"] <= 30][:15]
    return out


def _d(v):
    try:
        return date.fromisoformat(str(v)[:10])
    except (TypeError, ValueError):
        return None


def completeness(data, person=None):
    """Percent of the fields that have something in them. `person` is the person's own fields (for legacy ones)."""
    person = person if isinstance(person, dict) else {}
    total = sum(len(s["fields"]) for s in SECTIONS)
    filled = sum(len(v) for v in data.values())
    filled += sum(1 for s in SECTIONS for f in s["fields"] if f.get("legacy") and not empty(person.get(f["legacy"])))
    return min(100, round(100 * filled / total)) if total else 0


# ---------- text for the sensor and the AI ----------
def _show(f, v):
    if f["type"] == "tags":
        return ", ".join(v)
    if f["type"] == "check":
        return "yes" if v else "no"
    if f["type"] == "items":
        rows = []
        for r in v:
            rows.append(", ".join("%s: %s" % (sf["label"], ("yes" if r[sf["key"]] else "no") if sf["type"] == "check" else r[sf["key"]])
                                  for sf in f["fields"] if not empty(r.get(sf["key"]))))
        return " | ".join(rows)
    return str(v)


def section_text(sec, vals):
    lines = []
    for f in sec["fields"]:
        v = vals.get(f["key"])
        if not empty(v):
            lines.append("%s: %s" % (f["label"], _show(f, v)))
    return lines


def profile_text(data, flags, target):
    """target is 'sensor' or 'ai': only sections switched on for it."""
    parts = []
    for sec in SECTIONS:
        if not flags.get(sec["key"], {}).get(target):
            continue
        lines = section_text(sec, data.get(sec["key"], {}))
        if lines:
            parts.append("%s\n  " % sec["title"].upper() + "\n  ".join(lines))
    return "\n".join(parts)


def sensor_profile(data, flags):
    """The `profile` attribute: sections switched on for the sensor, as {section: {field label: value}}."""
    out = {}
    for sec in SECTIONS:
        if not flags.get(sec["key"], {}).get("sensor"):
            continue
        vals = data.get(sec["key"], {})
        sub = {}
        for f in sec["fields"]:
            v = vals.get(f["key"])
            if empty(v) or f.get("legacy"):
                continue
            sub[f["label"]] = [x for x in _show(f, v).split(" | ")] if f["type"] == "items" else v
        if sub:
            out[sec["title"]] = sub
    return out


def schema():
    return [{k: v for k, v in s.items()} for s in SECTIONS]
