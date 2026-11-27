"""Turns a Tuya device's data points (DPs) into Home Assistant entities, and converts values both ways.

Pure functions only (no network), so they are easy to test.

A device keeps a list of entity specs. Every spec has: id, platform, name, enabled, and the DP number(s) it uses.
  switch / binary_sensor / sensor / number / select:  {"dp": 1, "kind": "bool|int|enum|str", ...}
  light:  {"dp": <on/off>, "bright": {"dp","min","max"}, "ct": {"dp","min","max"}, "color": {"dp","fmt"}, "mode": {"dp"}}
"""
import json
import re

LIGHT_CATS = {"dj", "dd", "xdd", "fwd", "dc", "tgq", "tgkg", "fsd"}
ON_CODES = ("switch_led", "switch_led_1", "switch_light", "light")
BRIGHT_CODES = ("bright_value_v2", "bright_value", "bright_value_1")
CT_CODES = ("temp_value_v2", "temp_value", "temp_value_1")
COLOR_CODES = ("colour_data_v2", "colour_data", "colour_data_1")
MODE_CODES = ("work_mode",)
QUIET = re.compile(r"^(countdown|cycle_time|random_time)|_countdown(_\d+)?$")
KELVIN_MIN, KELVIN_MAX = 2700, 6500

TYPE_MAP = {"bool": "bool", "boolean": "bool", "value": "int", "integer": "int", "int": "int", "enum": "enum",
            "string": "str", "str": "str", "json": "str", "raw": "str", "bitmap": "str"}

# code -> (device_class, state_class) for sensors
SENSOR_CLASSES = {
    "cur_power": ("power", "measurement"), "cur_voltage": ("voltage", "measurement"),
    "cur_current": ("current", "measurement"), "add_ele": ("energy", "total_increasing"),
    "battery_percentage": ("battery", "measurement"), "va_battery": ("battery", "measurement"),
    "temp_current": ("temperature", "measurement"), "va_temperature": ("temperature", "measurement"),
    "humidity_value": ("humidity", "measurement"), "va_humidity": ("humidity", "measurement"),
}
UNITS = {"℃": "°C", "℉": "°F", "ma": "mA", "mA": "mA", "kwh": "kWh", "KWh": "kWh", "w": "W", "v": "V"}


def label(code):
    return re.sub(r"\s+", " ", re.sub(r"[_\s]+", " ", str(code))).strip().capitalize() or "Value"


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_")


def norm_type(t):
    return TYPE_MAP.get(str(t or "").strip().lower(), "str")


def parse_desc(v):
    if isinstance(v, dict):
        return v
    try:
        out = json.loads(v) if v else {}
        return out if isinstance(out, dict) else {}
    except (TypeError, ValueError):
        return {}


def _num(x, default):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def dp_from_cloud(item, writable_codes):
    """One DP row of /v1.0/m/life/devices/<id>/status -> our dp description."""
    desc = parse_desc(item.get("valueDesc"))
    code = str(item.get("statusCode") or item.get("code") or "")
    return {"dp": int(item["dpId"]), "code": code, "type": norm_type(item.get("valueType")),
            "desc": desc, "writable": code in writable_codes}


def build_entities(dps, category=""):
    """dps: list of {dp, code, type, desc, writable} -> list of entity specs (one per DP, lights grouped)."""
    by_code = {d["code"]: d for d in dps if d.get("code")}
    used, out = set(), []

    def first(codes):
        return next((by_code[c] for c in codes if c in by_code), None)

    on, bright = first(ON_CODES), first(BRIGHT_CODES)
    if on is None and bright is not None and category in LIGHT_CATS:
        on = by_code.get("switch") or by_code.get("switch_1")
    if on is not None and (bright is not None or category in LIGHT_CATS):
        ent = {"id": "light", "platform": "light", "name": "Light", "enabled": True, "dp": on["dp"]}
        used.add(on["code"])
        if bright:
            ds = bright["desc"]
            ent["bright"] = {"dp": bright["dp"], "min": _num(ds.get("min"), 10), "max": _num(ds.get("max"), 1000)}
            used.add(bright["code"])
        ct = first(CT_CODES)
        if ct:
            ds = ct["desc"]
            ent["ct"] = {"dp": ct["dp"], "min": _num(ds.get("min"), 0), "max": _num(ds.get("max"), 1000)}
            used.add(ct["code"])
        col = first(COLOR_CODES)
        if col:
            if col["code"].endswith("_v2"):
                ent["color"] = {"dp": col["dp"], "fmt": "v2"}
            used.add(col["code"])  # the older hex colour format is not supported: the light stays white only
        mode = first(MODE_CODES)
        if mode:
            ent["mode"] = {"dp": mode["dp"]}
            used.add(mode["code"])
        out.append(ent)

    if "power_go" in by_code or (category == "sd" and "status" in by_code):
        cfg = {"status": (by_code.get("status") or {}).get("dp") or by_code["power_go"]["dp"]}
        for key, code in (("go", "power_go"), ("power", "power"), ("battery", "electricity_left"), ("locate", "seek")):
            if code in by_code:
                cfg[key] = by_code[code]["dp"]
        if "mode" in by_code:
            cfg["mode"], cfg["mode_options"] = by_code["mode"]["dp"], [str(x) for x in by_code["mode"]["desc"].get("range") or []]
        if "suction" in by_code:
            cfg["fan"], cfg["fan_options"] = by_code["suction"]["dp"], [str(x) for x in by_code["suction"]["desc"].get("range") or []]
        out.append(vacuum_spec(cfg))
        used.update({"power", "power_go", "seek", "direction_control", "suction"})

    for d in dps:
        code = d.get("code") or f"dp_{d['dp']}"
        if code in used:
            continue
        kind, ds, writable = d.get("type", "str"), d.get("desc") or {}, bool(d.get("writable"))
        ent = {"id": slug(code) or f"dp_{d['dp']}", "name": label(code), "dp": d["dp"], "kind": kind,
               "enabled": not QUIET.search(code), "writable": writable}
        if kind == "bool":
            ent["platform"] = "switch" if writable else "binary_sensor"
        elif kind == "enum":
            ent["options"] = [str(x) for x in (ds.get("range") or [])]
            ent["platform"] = "select" if writable and ent["options"] else "sensor"
        elif kind == "int":
            ent["scale"] = int(_num(ds.get("scale"), 0))
            ent["min"], ent["max"], ent["step"] = (_num(ds.get("min"), 0) / 10 ** ent["scale"],
                                                  _num(ds.get("max"), 100) / 10 ** ent["scale"],
                                                  max(_num(ds.get("step"), 1) / 10 ** ent["scale"], 10 ** -ent["scale"]))
            unit = str(ds.get("unit") or "")
            ent["unit"] = UNITS.get(unit, UNITS.get(unit.lower(), unit))
            ent["platform"] = "number" if writable else "sensor"
        else:
            ent["platform"] = "sensor"
        cls = SENSOR_CLASSES.get(code)
        if cls and ent["platform"] == "sensor":
            ent["device_class"], ent["state_class"] = cls
        out.append(ent)
    ids = {}
    for e in out:  # keep ids unique
        n = ids.get(e["id"], 0)
        ids[e["id"]] = n + 1
        if n:
            e["id"] += f"_{n + 1}"
    return out


def merge_entities(old, new):
    """After a cloud sync: new specs, but keep what the user changed (enabled, name) for entities with the same id."""
    keep = {e["id"]: e for e in old or []}
    for e in new:
        o = keep.get(e["id"])
        if o:
            e["enabled"] = o.get("enabled", e["enabled"])
            if o.get("name"):
                e["name"] = o["name"]
            if o.get("labels"):
                e["labels"] = o["labels"]
            if isinstance(o.get("fan"), dict) and isinstance(e.get("fan"), dict) and o["fan"].get("labels"):
                e["fan"]["labels"] = o["fan"]["labels"]
    return new


def entities_from_values(values, taken=()):
    """Guess entities from what a device reports (used when there is no cloud list): true/false DPs become
    switches, numbers and text become sensors. Skips DP numbers already used by another entity."""
    out = []
    for k, v in sorted(values.items(), key=lambda kv: int(kv[0])):
        dp = int(k)
        if dp in taken:
            continue
        ent = {"id": f"dp_{dp}", "name": f"DP {dp}", "dp": dp, "enabled": False}  # unnamed: shown only if the user turns them on
        if isinstance(v, bool):
            ent.update(platform="switch", kind="bool", writable=True)
        elif isinstance(v, (int, float)):
            ent.update(platform="sensor", kind="int", scale=0, writable=False)
        else:
            ent.update(platform="sensor", kind="str", writable=False)
        out.append(ent)
    return out

# ---------- robot vacuums ----------
VAC_STATE = {
    "cleaning": "cleaning", "smart": "cleaning", "zone_clean": "cleaning", "part_clean": "cleaning", "pose": "cleaning",
    "goto_pos": "cleaning", "pos_arrived": "cleaning", "pos_unarrive": "cleaning", "mop": "cleaning", "spot": "cleaning",
    "goto_charge": "returning", "chargego": "returning", "docking": "returning", "returning": "returning",
    "charging": "docked", "charge_done": "docked", "docked": "docked", "paused": "paused", "pause": "paused",
    "standby": "idle", "sleep": "idle", "stop": "idle", "idle": "idle", "fault": "error", "error": "error",
}
VAC_DIRECTION = {"forward", "backward", "turn_left", "turn_right", "stop"}
VAC_MODE_WORDS = {"smart", "zone", "pose", "part", "chargego", "standby", "auto", "spot", "edge", "mop", "single", "spiral"}


def guess_vacuum(values, entities):
    """Best guess of a vacuum's data points from what it reports now and the entities already made for it."""
    vals = {}
    for k, v in (values or {}).items():
        try:
            vals[int(k)] = v
        except ValueError:
            pass

    def sv(dp):
        v = vals.get(dp)
        return v.lower() if isinstance(v, str) else None

    status = 5 if sv(5) in VAC_STATE else next(
        (dp for dp in sorted(vals) if sv(dp) in VAC_STATE and sv(dp) not in VAC_DIRECTION and sv(dp) != "standby"), None)
    direction = next((dp for dp in sorted(vals) if sv(dp) in VAC_DIRECTION and dp != status), None)
    battery = next((e["dp"] for e in entities if e.get("platform") == "sensor" and ("battery" in e["name"].lower() or e.get("device_class") == "battery")), None)
    if battery is None and isinstance(vals.get(6), int) and 0 <= vals[6] <= 100:
        battery = 6
    mode = next((e for e in entities if e.get("platform") == "select" and VAC_MODE_WORDS & set(e.get("options", []))), None)
    return {"status": status, "go": 2 if isinstance(vals.get(2), bool) else None, "power": 1 if isinstance(vals.get(1), bool) else None,
            "mode": mode["dp"] if mode else None, "mode_options": list(mode.get("options", [])) if mode else [],
            "battery": battery, "direction": direction, "fan": None, "fan_options": [], "locate": None}


def vacuum_spec(cfg):
    """Entity spec for a vacuum from {status, go, power, mode, mode_options, battery, fan, fan_options, locate}."""
    ent = {"id": "vacuum", "platform": "vacuum", "name": "Vacuum", "enabled": True, "dp": int(cfg["status"]), "kind": "enum"}
    for k in ("power", "go", "battery", "locate"):
        if cfg.get(k):
            ent[k] = {"dp": int(cfg[k])}
    if cfg.get("mode"):
        ent["mode"] = {"dp": int(cfg["mode"]), "options": [str(x) for x in cfg.get("mode_options") or []]}
    if cfg.get("fan"):
        ent["fan"] = {"dp": int(cfg["fan"]), "options": [str(x) for x in cfg.get("fan_options") or []], "labels": {}}
    return ent


def apply_vacuum(entities, spec, extra_hidden=()):
    """Put the vacuum in the entity list and hide what it replaces (its on/off, start, locate, direction and fan data
    points, and any plain 'DP n' entities). Battery, status and the mode select stay."""
    gone = {spec[k]["dp"] for k in ("power", "go", "locate", "fan") if isinstance(spec.get(k), dict)} | set(extra_hidden)
    out = [dict(e) for e in entities if e["id"] != "vacuum"]
    for e in out:
        if e.get("dp") in gone or re.fullmatch(r"DP \d+", e["name"]):
            e["enabled"] = False
    return [spec] + out


def vacuum_state(ent, dps):
    raw = dps.get(str(ent["dp"]))
    if raw is None:
        return None
    key = str(raw).lower()
    out = {"state": (ent.get("status_map") or {}).get(key) or VAC_STATE.get(key, "idle")}
    b = ent.get("battery")
    if b and isinstance(dps.get(str(b["dp"])), (int, float)):
        out["battery_level"] = max(0, min(100, int(dps[str(b["dp"])])))
    f = ent.get("fan")
    if f and dps.get(str(f["dp"])) is not None:
        out["fan_speed"] = (f.get("labels") or {}).get(str(dps[str(f["dp"])]), str(dps[str(f["dp"])]))
    return json.dumps(out)


def vacuum_command(ent, text):
    t = text.strip()
    f = ent.get("fan")
    if t.startswith("fan:") and f:
        label = t[4:]
        raw = next((r for r, lab in (f.get("labels") or {}).items() if lab == label), label)
        return {f["dp"]: raw}
    t = t.lower()
    go, power, mode, loc = ent.get("go"), ent.get("power"), ent.get("mode"), ent.get("locate")
    modes = (mode or {}).get("options", [])
    if t == "start":
        if go:
            out = {power["dp"]: True} if power else {}
            out[go["dp"]] = True
            return out
        pick = next((m for m in ("smart", "auto") if m in modes), None)
        return {mode["dp"]: pick} if mode and pick else {}
    if t == "pause":
        return {go["dp"]: False} if go else {}
    if t == "stop":
        if mode and "standby" in modes:
            return {mode["dp"]: "standby"}
        return {go["dp"]: False} if go else {}
    if t == "return_to_base":
        pick = next((m for m in ("chargego", "charge", "return") if m in modes), None)
        return {mode["dp"]: pick} if mode and pick else {}
    if t == "locate":
        return {loc["dp"]: True} if loc else {}
    return {}



# ---------- values ----------
def dps_used(ent):
    return [ent[k]["dp"] for k in ("bright", "ct", "color", "mode", "power", "go", "battery", "locate", "fan") if isinstance(ent.get(k), dict)] + [ent["dp"]]


def _scale(ent):
    return 10 ** int(ent.get("scale") or 0)


def _lin(x, a, b, c, d):
    """Map x from [a, b] to [c, d]."""
    if b == a:
        return c
    return c + (x - a) * (d - c) / (b - a)


def entity_state(ent, dps):
    """The payload to publish for an entity, or None when the device hasn't reported its DP yet."""
    if ent["platform"] == "light":
        return light_state(ent, dps)
    if ent["platform"] == "vacuum":
        return vacuum_state(ent, dps)
    raw = dps.get(str(ent["dp"]))
    if raw is None:
        return None
    kind = ent.get("kind")
    if ent.get("labels") and not isinstance(raw, bool):
        return ent["labels"].get(str(raw), str(raw))
    if ent["platform"] in ("switch", "binary_sensor"):
        return "ON" if raw in (True, 1, "true", "True") else "OFF"
    if kind == "int":
        try:
            v = float(raw) / _scale(ent)
        except (TypeError, ValueError):
            return None
        return str(int(v)) if ent.get("scale", 0) == 0 else str(round(v, int(ent["scale"])))
    return raw if isinstance(raw, str) else json.dumps(raw)


def light_state(ent, dps):
    on = dps.get(str(ent["dp"]))
    if on is None:
        return None
    out = {"state": "ON" if on else "OFF"}
    mode = dps.get(str(ent["mode"]["dp"])) if ent.get("mode") else None
    b = ent.get("bright")
    if b and dps.get(str(b["dp"])) is not None:
        out["brightness"] = int(round(_lin(float(dps[str(b["dp"])]), b["min"], b["max"], 1, 255)))
    ct = ent.get("ct")
    if ct and dps.get(str(ct["dp"])) is not None:
        out["color_temp"] = int(round(_lin(float(dps[str(ct["dp"])]), ct["min"], ct["max"], KELVIN_MIN, KELVIN_MAX)))
    col = ent.get("color")
    out["color_mode"] = "hs" if (col and mode == "colour") else "color_temp" if ct else "brightness" if b else "onoff"
    if col and mode == "colour":
        try:
            c = json.loads(dps.get(str(col["dp"])) or "{}")
            out["color"] = {"h": float(c.get("h", 0)), "s": float(c.get("s", 0)) / 10}
            out["brightness"] = int(round(_lin(float(c.get("v", 1000)), 0, 1000, 1, 255)))
        except (TypeError, ValueError):
            pass
    return json.dumps(out)


def entity_command(ent, payload):
    """What to send for a command from Home Assistant: {dp number: value}, or {} if it makes no sense."""
    p = ent["platform"]
    text = payload.strip() if isinstance(payload, str) else str(payload)
    if p == "switch":
        return {ent["dp"]: text.upper() == "ON"} if ent.get("writable", True) else {}
    if p == "number":
        try:
            return {ent["dp"]: int(round(float(text) * _scale(ent)))}
        except ValueError:
            return {}
    if p == "select":
        raw = next((r for r in ent.get("options", []) if (ent.get("labels") or {}).get(r, r) == text), None)
        return {ent["dp"]: raw} if raw is not None else {}
    if p == "light":
        return light_command(ent, text)
    if p == "vacuum":
        return vacuum_command(ent, text)
    return {}


def light_command(ent, text):
    try:
        req = json.loads(text)
    except ValueError:
        req = {"state": text}
    if not isinstance(req, dict):
        return {}
    out = {}
    if "state" in req:
        out[ent["dp"]] = str(req["state"]).upper() == "ON"
    b, ct, col, mode = ent.get("bright"), ent.get("ct"), ent.get("color"), ent.get("mode")
    if "brightness" in req and b:
        out[b["dp"]] = int(round(_lin(float(req["brightness"]), 1, 255, b["min"], b["max"])))
        out[ent["dp"]] = True
        if mode and "color" not in req and "color_temp" not in req:
            out[mode["dp"]] = "white"
    if "color_temp" in req and ct:
        k = min(max(float(req["color_temp"]), KELVIN_MIN), KELVIN_MAX)
        out[ct["dp"]] = int(round(_lin(k, KELVIN_MIN, KELVIN_MAX, ct["min"], ct["max"])))
        out[ent["dp"]] = True
        if mode:
            out[mode["dp"]] = "white"
    if "color" in req and col and isinstance(req["color"], dict):
        v = _lin(float(req.get("brightness", 255)), 1, 255, 0, 1000)
        out[col["dp"]] = json.dumps({"h": int(round(float(req["color"].get("h", 0)))),
                                     "s": int(round(float(req["color"].get("s", 0)) * 10)), "v": int(round(v))},
                                    separators=(",", ":"))
        out[ent["dp"]] = True
        if mode:
            out[mode["dp"]] = "colour"
    return out


# ---------- Home Assistant MQTT discovery ----------
def discovery(dev, ent, base="tuya_local"):
    """(topic, payload) of the MQTT discovery message for one entity."""
    did, eid = dev["id"], ent["id"]
    uid = f"tuya_local_{did}_{eid}"
    tbase = f"{base}/{did}/{eid}"
    p = ent["platform"]
    dname = str(dev.get("name") or did)
    # every entity lives under ONE Home Assistant device, so the Tuya device's name goes in front of the entity's name
    words, dwords = set(re.findall(r"[a-z0-9]+", ent["name"].lower())), set(re.findall(r"[a-z0-9]+", dname.lower()))
    if ent["platform"] == "vacuum" or (words and words <= dwords):
        full = dname  # the entity's name only repeats the device's (Living Lamp / Living Room Lamp)
    elif ent["name"].lower().startswith(dname.lower()):
        full = ent["name"]
    else:
        full = f"{dname} {ent['name']}"
    cfg = {
        "name": full, "unique_id": uid, "default_entity_id": f"{p}.{slug(full)}",
        "state_topic": f"{tbase}/state",
        "availability": [{"topic": f"{base}/status"}, {"topic": f"{base}/{did}/available"}],
        "availability_mode": "all",
        "device": {"identifiers": ["tuya_local_hub"], "name": "Local Devices", "manufacturer": "Tuya", "model": "Local control"},
    }
    if p in ("switch", "number", "select", "light", "vacuum"):
        cfg["command_topic"] = f"{tbase}/set"
    if p == "switch":
        cfg.update(payload_on="ON", payload_off="OFF")
    elif p == "binary_sensor":
        cfg.update(payload_on="ON", payload_off="OFF")
    elif p == "number":
        cfg.update(min=ent.get("min", 0), max=ent.get("max", 100), step=ent.get("step", 1), mode="box")
        if ent.get("unit"):
            cfg["unit_of_measurement"] = ent["unit"]
    elif p == "select":
        labels = ent.get("labels") or {}
        cfg["options"] = [labels.get(o, o) for o in ent.get("options", [])]
    elif p == "sensor":
        if ent.get("unit"):
            cfg["unit_of_measurement"] = ent["unit"]
        for k in ("device_class", "state_class"):
            if ent.get(k):
                cfg[k] = ent[k]
        if ent.get("kind") == "enum":
            cfg["entity_category"] = "diagnostic"
    elif p == "vacuum":
        feats = ["start", "pause", "stop", "return_home", "status"]
        if ent.get("battery"):
            feats.append("battery")
        if ent.get("locate"):
            feats.append("locate")
        cfg.update(command_topic=f"{tbase}/set", payload_start="start", payload_pause="pause", payload_stop="stop",
                   payload_return_to_base="return_to_base", payload_locate="locate", supported_features=feats)
        if ent.get("fan"):
            lab = ent["fan"].get("labels") or {}
            cfg["supported_features"].append("fan_speed")
            cfg["set_fan_speed_topic"] = f"{tbase}/fan"
            cfg["fan_speed_list"] = [lab.get(o, o) for o in ent["fan"].get("options", [])]
    elif p == "light":
        modes = []
        if ent.get("color"):
            modes.append("hs")
        if ent.get("ct"):
            modes.append("color_temp")
        if not modes:
            modes.append("brightness" if ent.get("bright") else "onoff")
        cfg.update(schema="json", supported_color_modes=modes, color_mode=True,
                   brightness=bool(ent.get("bright") or ent.get("color")),
                   min_kelvin=KELVIN_MIN, max_kelvin=KELVIN_MAX)
    if ent.get("kind") in ("str",) and p == "sensor":
        cfg["entity_category"] = "diagnostic"
    return f"homeassistant/{p}/{uid}/config", cfg
