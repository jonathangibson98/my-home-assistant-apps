"""More entities for Personalized Info.

Besides the fixed roles (person, phone, asleep, ...), each person can be linked to any number of
extra Home Assistant entities (heart rate, steps, which room they are in, their car, a smart lock...)
and the house can have its own list (weather, alarm, house mode...). Their current values go into
the info sensor, and into the one-line status the AI reads.

Stored on a person as links.more (a list) and for the house in /data/settings.json under "house".
Each entry: {"entity_id": "sensor.x", "label": "optional", "attributes": "a,b", "say": true}
"""
import re

ENTITY_ID = re.compile(r"[a-z0-9_]+\.[a-z0-9_]+")
NO_VALUE = ("unknown", "unavailable", "")
MAX_PER_PERSON = 60
MAX_HOUSE = 40
VALUE_CHARS = 300

# What a binary sensor's on/off means, by device class
BINARY_WORDS = {
    "door": ("open", "closed"), "window": ("open", "closed"), "garage_door": ("open", "closed"),
    "opening": ("open", "closed"), "lock": ("unlocked", "locked"),
    "motion": ("motion", "clear"), "occupancy": ("occupied", "clear"), "presence": ("home", "away"),
    "moisture": ("wet", "dry"), "smoke": ("smoke", "clear"), "gas": ("gas", "clear"),
    "battery": ("low", "normal"), "connectivity": ("connected", "disconnected"),
    "running": ("running", "not running"), "problem": ("problem", "ok"), "safety": ("unsafe", "safe"),
    "plug": ("plugged in", "unplugged"), "battery_charging": ("charging", "not charging"),
}

# Companion app sensors that are picked up on their own once the phone is linked
PHONE_AUTO = {"is_charging", "battery_state", "battery_level", "activity", "ssid", "wi_fi_connection", "steps"}


def slug(t):
    return re.sub(r"[^a-z0-9]+", "_", str(t).lower()).strip("_")


def clean_item(raw):
    """One extra entity as {"entity_id", "label"?, "attributes"?, "say"}, or None when it isn't usable."""
    if isinstance(raw, str):
        raw = {"entity_id": raw}
    if not isinstance(raw, dict):
        return None
    eid = str(raw.get("entity_id") or "").strip().lower()
    if not ENTITY_ID.fullmatch(eid):
        return None
    out = {"entity_id": eid}
    label = str(raw.get("label") or "").strip()[:80]
    if label:
        out["label"] = label
    attrs = raw.get("attributes")
    if isinstance(attrs, (list, tuple)):
        attrs = ", ".join(str(a) for a in attrs)
    attrs = str(attrs or "").strip()[:300]
    if attrs:
        out["attributes"] = attrs
    out["say"] = raw.get("say") is not False
    return out


def clean_items(raw, limit=MAX_PER_PERSON):
    """A list of usable extra entities, no duplicates, in the order given."""
    out, seen = [], set()
    for it in raw if isinstance(raw, list) else []:
        c = clean_item(it)
        if c and c["entity_id"] not in seen:
            seen.add(c["entity_id"])
            out.append(c)
        if len(out) >= limit:
            break
    return out


def clean_all(d):
    """Drop unusable extra entities (blank rows from the page) from everyone's links, before saving."""
    for g in ("household", "friends"):
        for p in (d.get(g) or {}).values():
            links = p.get("links") if isinstance(p, dict) else None
            if not isinstance(links, dict) or "more" not in links:
                continue
            items = clean_items(links["more"])
            if items:
                links["more"] = items
            else:
                links.pop("more", None)
            if not links:
                p.pop("links", None)
    return d


def entities_view(links):
    """What the sensor's `entities` attribute shows for a person: the roles, plus the extra entity ids."""
    if not isinstance(links, dict):
        return links
    out = {r: v for r, v in links.items() if r != "more"}
    more = [i["entity_id"] for i in clean_items(links.get("more"))]
    if more:
        out["more"] = more
    return out


def _pretty(t):
    return str(t).replace("_", " ").strip()


def _label(item, state):
    if item.get("label"):
        return item["label"]
    name = (state.get("attributes") or {}).get("friendly_name")
    return str(name).strip() if name else _pretty(item["entity_id"].split(".", 1)[1])


def _short(v):
    if isinstance(v, (list, tuple)):
        v = ", ".join(str(x) for x in v)
    elif isinstance(v, dict):
        v = ", ".join(f"{k}: {x}" for k, x in v.items())
    return str(v)[:VALUE_CHARS]


def _binary_word(state):
    """(word for on/off, or None) for a binary sensor with a known device class."""
    if not str(state.get("entity_id", "")).startswith("binary_sensor."):
        return None
    words = BINARY_WORDS.get((state.get("attributes") or {}).get("device_class"))
    if not words or state["state"] not in ("on", "off"):
        return None
    return words[0] if state["state"] == "on" else words[1]


def _value(state):
    word = _binary_word(state)
    if word:
        return word
    unit = (state.get("attributes") or {}).get("unit_of_measurement")
    return _short(f"{state['state']} {unit}" if unit else state["state"])


def extra_entities(items, states, terse=True):
    """({label: value}, [words for the one-line status]) for a list of extra entities.

    terse: a plain on/off sensor only speaks when it is on (people's status line). The house text
    always says on or off.
    """
    out, words = {}, []
    for it in clean_items(items, MAX_PER_PERSON if terse else MAX_HOUSE):
        st = states.get(it["entity_id"])
        if not st or st.get("state") in NO_VALUE:
            continue
        st = dict(st, entity_id=it["entity_id"])
        label = _label(it, st)
        val = _value(st)
        wanted = [a.strip() for a in (it.get("attributes") or "").split(",") if a.strip()]
        attrs = st.get("attributes") or {}
        shown = {a: _short(attrs[a]) for a in wanted if a in attrs and attrs[a] not in (None, "")}
        key = label if label not in out else f"{label} ({it['entity_id']})"
        out[key] = {"state": val, **shown} if shown else val
        if not it.get("say"):
            continue
        text = val if not shown else f"{val}, " + ", ".join(f"{a} {v}" for a, v in shown.items())
        if terse and st["state"] in ("on", "off") and not _binary_word(st):
            if st["state"] == "on":
                words.append(label)
        else:
            words.append(f"{label}: {text}")
    return out, words


def house_summary(items, states):
    """(values by label, text with one line per entity) for the house list."""
    values, words = extra_entities(items, states, terse=False)
    return values, "\n".join(words)


def phone_extras(base, states):
    """More about the phone, from the Companion app's own sensors. base is the device tracker's name."""
    out, words = {}, []

    def pick(*ids):
        for i in ids:
            eid = i.format(b=base)
            s = states.get(eid)
            if s and s.get("state") not in NO_VALUE:
                return dict(s, entity_id=eid)
        return None

    s = pick("binary_sensor.{b}_is_charging", "sensor.{b}_battery_state")
    if s:
        on = s["state"] == "on" if s["entity_id"].startswith("binary_sensor.") else str(s["state"]).lower() == "charging"
        out["phone_charging"] = on
    s = pick("sensor.{b}_activity")
    if s:
        out["phone_activity"] = s["state"]
        if str(s["state"]).lower() not in ("stationary", "still", "unknown", "none"):
            words.append(_pretty(s["state"]).lower())
    s = pick("sensor.{b}_ssid", "sensor.{b}_wi_fi_connection")
    if s:
        out["phone_wifi"] = s["state"]
    s = pick("sensor.{b}_steps")
    if s:
        out["steps"] = s["state"]
    return out, words


def _strip_prefix(name, prefixes):
    for pre in prefixes:
        pre = str(pre or "").strip()
        if pre and name.lower().startswith(pre.lower()):
            rest = name[len(pre):].strip(" -_:")
            if rest:
                return rest
    return name


SUGGEST_DOMAINS = ("sensor.", "binary_sensor.", "device_tracker.", "media_player.", "calendar.", "weather.", "climate.",
                   "lock.", "cover.", "input_boolean.", "input_select.", "input_text.", "input_number.", "select.",
                   "switch.", "light.", "number.", "vacuum.", "alarm_control_panel.", "todo.")


def suggest_more(key, person, states, linked=()):
    """Entities that probably belong to this person: the phone app's sensors, and anything named after them.

    linked: entity ids that are already linked (roles and extras), left out.
    """
    links = person.get("links") if isinstance(person.get("links"), dict) else {}
    taken = set(linked) | {v for r, v in links.items() if r != "more" and isinstance(v, str)}
    taken |= {i["entity_id"] for i in clean_items(links.get("more"))}
    names = {slug(key), slug(person.get("name") or "")} - {""}
    names = {n for n in names if len(n) >= 3}
    out, seen = [], set()

    def add(eid, group, prefixes=()):
        if eid in seen or eid in taken or not eid.startswith(SUGGEST_DOMAINS):
            return
        s = states.get(eid) or {}
        friendly = (s.get("attributes") or {}).get("friendly_name") or eid
        seen.add(eid)
        out.append({"entity_id": eid, "name": str(friendly), "label": _strip_prefix(str(friendly), prefixes),
                    "state": str(s.get("state"))[:40], "group": group})

    phone = str(links.get("phone") or "")
    if phone.startswith("device_tracker."):
        base = phone.split(".", 1)[1]
        pname = ((states.get(phone) or {}).get("attributes") or {}).get("friendly_name") or ""
        n = 0
        for eid in sorted(states):
            obj = eid.split(".", 1)[1]
            if eid.startswith(("sensor.", "binary_sensor.")) and obj.startswith(base + "_") \
                    and obj[len(base) + 1:] not in PHONE_AUTO:
                add(eid, "Phone app", (pname, person.get("name")))
                n += 1
                if n >= 50:
                    break
    n = 0
    for eid in sorted(states):
        obj = eid.split(".", 1)[1]
        if eid.startswith("person.") or not any(obj == nm or obj.startswith(nm + "_") or f"_{nm}_" in f"_{obj}_"
                                                for nm in names):
            continue
        add(eid, f"Named after {person.get('name') or key}", (person.get("name"),))
        n += 1
        if n >= 40:
            break
    return out
