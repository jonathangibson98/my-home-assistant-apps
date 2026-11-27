"""Tuya account access (QR code login, same method Home Assistant's own Tuya integration uses) and the
LocalTuya importer. Both only produce plain device dicts for run.py to store."""
import json
import math

import segno
import tuya_sharing

import tuya_model as M

CLIENT_ID = "HA_3y9q4ak7g4ephrvke"   # the public client Home Assistant's Tuya integration uses for QR login
SCHEMA = "haauthorize"


# ---------- QR login ----------
def qr_start(user_code):
    """Ask Tuya for a login QR code. Returns {token, text, svg}."""
    r = tuya_sharing.LoginControl().qr_code(CLIENT_ID, SCHEMA, user_code.strip())
    if not r.get("success"):
        raise RuntimeError(r.get("msg") or "Tuya did not accept that User Code. Check it in the app and try again.")
    token = r["result"]["qrcode"]
    text = f"tuyaSmart--qrLogin?token={token}"
    svg = segno.make(text, error="m").svg_inline(scale=6, border=2, dark="#000000", light="#ffffff")
    return {"token": token, "text": text, "svg": svg}


def qr_poll(token, user_code):
    """(True, auth) once the QR code was scanned in the app, else (False, message)."""
    ok, info = tuya_sharing.LoginControl().login_result(token, CLIENT_ID, user_code.strip())
    if not ok:
        return False, str(info.get("msg") or "waiting")
    auth = {"user_code": user_code.strip(), "terminal_id": info.get("terminal_id", ""), "endpoint": info.get("endpoint", ""),
            "token": {k: info.get(k) for k in ("t", "expire_time", "uid", "access_token", "refresh_token")}}
    return True, auth


class _Keep(tuya_sharing.SharingTokenListener):
    def __init__(self, auth, save):
        self.auth, self.save = auth, save

    def update_token(self, token_info):
        self.auth["token"] = dict(token_info)
        self.save()


def fetch_devices(auth, save):
    """Every device on the account with its local key and DP list. save() is called when the login token refreshes."""
    mgr = tuya_sharing.Manager(CLIENT_ID, auth["user_code"], auth["terminal_id"], auth["endpoint"], auth["token"],
                               _Keep(auth, save))
    mgr.update_device_cache()
    out = []
    for d in mgr.device_map.values():
        writable = set((getattr(d, "function", None) or {}).keys())
        dps = []
        try:
            r = mgr.customer_api.get(f"/v1.0/m/life/devices/{d.id}/status")
            for item in (r.get("result") or {}).get("dpStatusRelationDTOS") or []:
                try:
                    dps.append(M.dp_from_cloud(item, writable))
                except (KeyError, ValueError, TypeError):
                    continue
        except Exception:
            pass
        out.append({"id": d.id, "name": d.name, "key": getattr(d, "local_key", "") or "", "category": d.category or "",
                    "product_id": d.product_id or "", "product_name": getattr(d, "product_name", "") or "",
                    "sub": bool(getattr(d, "sub", False)), "online": bool(getattr(d, "online", False)), "dps": dps})
    return out


# ---------- LocalTuya import ----------
SUPPORTED = {"switch", "light", "sensor", "binary_sensor", "number", "select"}


def _find(obj, out, hint=None):
    """Walk any JSON and collect dicts that look like a LocalTuya device (they have a local_key)."""
    if isinstance(obj, dict):
        key = obj.get("local_key") or obj.get("localkey")
        did = obj.get("device_id") or obj.get("devId") or obj.get("id") or hint
        if key and isinstance(did, str) and did and not isinstance(obj.get("id"), int):
            out[did] = obj
            return
        for k, v in obj.items():
            _find(v, out, k if isinstance(k, str) else None)
    elif isinstance(obj, list):
        for v in obj:
            _find(v, out)


def _int(x):
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _entity(e, did):
    """One LocalTuya entity -> our spec, or None if it isn't one we handle."""
    plat, dp = str(e.get("platform") or ""), _int(e.get("id"))
    if plat not in SUPPORTED or dp is None:
        return None
    name = str(e.get("friendly_name") or e.get("name") or f"{M.label(plat)} {dp}")
    spec = {"id": f"{plat}_{dp}", "platform": plat, "name": name, "enabled": True, "dp": dp, "writable": plat not in ("sensor", "binary_sensor")}
    if plat in ("switch", "binary_sensor"):
        spec["kind"] = "bool"
    elif plat == "sensor":
        sc = e.get("scaling")
        try:
            spec["scale"] = max(0, int(round(-math.log10(float(sc))))) if sc and float(sc) not in (0, 1) else 0
        except (TypeError, ValueError):
            spec["scale"] = 0
        spec["kind"] = "int" if sc else "str"
        if e.get("unit_of_measurement"):
            spec["unit"] = str(e["unit_of_measurement"])
        if e.get("device_class"):
            spec["device_class"] = str(e["device_class"])
    elif plat == "number":
        try:
            sc = float(e.get("scaling") or 1)
        except (TypeError, ValueError):
            sc = 1
        spec["kind"] = "int"
        spec["scale"] = max(0, int(round(-math.log10(sc)))) if sc not in (0, 1) else 0
        spec["min"], spec["max"] = float(e.get("min_value", 0)), float(e.get("max_value", 100))
        spec["step"] = float(e.get("step_size", 1) or 1)
        if e.get("unit_of_measurement"):
            spec["unit"] = str(e["unit_of_measurement"])
    elif plat == "select":
        spec["kind"] = "enum"
        spec["options"] = [o for o in str(e.get("select_options") or "").split(";") if o]
        if not spec["options"]:
            return None
    elif plat == "light":
        spec["id"] = "light" if not e.get("_second") else f"light_{dp}"
        spec["kind"] = "bool"
        b = _int(e.get("brightness"))
        if b:
            spec["bright"] = {"dp": b, "min": float(e.get("brightness_lower", 29)), "max": float(e.get("brightness_upper", 1000))}
        ct = _int(e.get("color_temp"))
        if ct:
            spec["ct"] = {"dp": ct, "min": 0.0, "max": 1000.0}
        mode = _int(e.get("color_mode"))
        if mode:
            spec["mode"] = {"dp": mode}
    return spec


def parse_localtuya(text):
    """Devices from LocalTuya's saved config (core.config_entries) or any JSON that holds them. Returns
    (devices, skipped) where skipped lists entity platforms this add-on doesn't map by hand."""
    found, devices, skipped = {}, [], set()
    _find(json.loads(text), found)
    for did, d in found.items():
        ents, seen = [], set()
        for e in d.get("entities") or []:
            if not isinstance(e, dict):
                continue
            spec = _entity(e, did)
            if spec is None:
                if e.get("platform"):
                    skipped.add(str(e["platform"]))
                continue
            while spec["id"] in seen:
                spec["id"] += "_2"
            seen.add(spec["id"])
            ents.append(spec)
        ver = str(d.get("protocol_version") or d.get("version") or "auto")
        devices.append({"id": did, "name": str(d.get("friendly_name") or d.get("name") or did), "ip": str(d.get("host") or d.get("ip") or ""),
                        "key": str(d.get("local_key") or d.get("localkey") or ""),
                        "version": ver if ver in ("3.1", "3.2", "3.3", "3.4", "3.5") else "auto",
                        "entities": ents, "needs_inference": True})
    return devices, sorted(skipped)
