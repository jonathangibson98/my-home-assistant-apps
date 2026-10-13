"""iCloud Lite add-on: track Apple devices from multiple iCloud accounts, publish via MQTT."""
import asyncio
import hashlib
import html
import json
import logging
import math
import os
import secrets
import time
from pathlib import Path

import aiohttp
import paho.mqtt.client as mqtt
from aiohttp import web
from pyicloud import PyiCloudService

DATA = Path(os.getenv("DATA_DIR", "/data"))
ACCOUNTS_FILE = DATA / "accounts.json"
COOKIES = DATA / "cookies"
PREFIX = "icloud_lite"
STATUS_TOPIC = f"{PREFIX}/status"
INGRESS_IPS = {"172.30.32.2", "127.0.0.1", "::1"}
LOGIN_RETRY_SECONDS = 1800  # never hammer Apple after a failed login

log = logging.getLogger(PREFIX)


# ───────────────────────── MQTT ─────────────────────────
class Mqtt:
    def __init__(self):
        self.client = None
        self.connected = False
        self.generation = 0  # bumps on every (re)connect so discovery gets resent

    def start(self, host, port, user, password):
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{PREFIX}_addon")
        if user:
            client.username_pw_set(user, password or None)
        client.will_set(STATUS_TOPIC, "offline", retain=True)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.connect_async(host, int(port))
        client.loop_start()
        self.client = client

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if not getattr(reason_code, "is_failure", False):
            log.info("MQTT connected")
            client.publish(STATUS_TOPIC, "online", retain=True)
            self.generation += 1
            self.connected = True
        else:
            log.error("MQTT connect failed: %s", reason_code)

    def _on_disconnect(self, client, userdata, *args):
        self.connected = False
        log.warning("MQTT disconnected")

    def pub(self, topic, payload, retain=True):
        if not self.client or not self.connected:
            return
        if not isinstance(payload, (str, bytes)) and payload is not None:
            payload = json.dumps(payload)
        self.client.publish(topic, payload if payload is not None else "", retain=retain)


def distance_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in meters."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# ──────────────────────── Accounts ────────────────────────
class Account:
    def __init__(self, cfg):
        self.id = cfg["id"]
        self.username = cfg["username"]
        self.password = cfg["password"]
        self.interval = int(cfg.get("interval", 5))
        self.fast_interval = int(cfg.get("fast_interval", 60))  # seconds near zones, 0 = off
        self.near_distance = int(cfg.get("near_distance", 1500))  # meters outside a zone edge
        self.poll_note = ""
        self.selected = list(cfg.get("devices", []))
        self.names = dict(cfg.get("names", {}))  # device_id -> custom name for HA
        self.label = cfg.get("label", "")  # tab name in the web UI
        self.api = None
        self.status = "login"  # login | needs_2fa | ok | error
        self.message = ""
        self.devices = {}  # device_id -> name (everything on the account)
        self.info = {}  # device_id -> latest data
        self.next_login = 0.0
        self.next_poll = 0.0
        self.last_ok = None
        self.discovered = set()
        self.gen = -1
        self.alock = asyncio.Lock()

    def to_cfg(self):
        return {
            "id": self.id,
            "username": self.username,
            "password": self.password,
            "interval": self.interval,
            "fast_interval": self.fast_interval,
            "near_distance": self.near_distance,
            "devices": self.selected,
            "names": self.names,
            "label": self.label,
        }

    # ---- blocking pyicloud calls (always run in a thread) ----
    def login(self):
        COOKIES.mkdir(parents=True, exist_ok=True)
        self.next_login = time.time() + LOGIN_RETRY_SECONDS
        try:
            self.api = PyiCloudService(
                self.username, self.password, cookie_directory=str(COOKIES), with_family=True
            )
            if self.api.requires_2fa:
                self.status = "needs_2fa"
                self.message = "Apple needs a verification code."
                self.send_code()
                return
            self.status = "ok"
            self.message = ""
            self.fetch(locate=False)
        except Exception as err:  # noqa: BLE001
            self.status = "error"
            self.message = f"Login failed: {err}"
            log.warning("%s: %s", self.username, self.message)

    def send_code(self):
        try:
            self.api.request_2fa_code()
        except Exception as err:  # noqa: BLE001
            log.warning("%s: couldn't request 2FA code: %s", self.username, err)

    def verify(self, code):
        try:
            ok = self.api.validate_2fa_code(code.strip())
            if ok and not self.api.is_trusted_session:
                self.api.trust_session()
        except Exception as err:  # noqa: BLE001
            self.message = f"Code check failed: {err}"
            return
        if ok:
            self.status = "ok"
            self.message = ""
            try:
                self.fetch(locate=False)
            except Exception as err:  # noqa: BLE001
                self.message = f"Logged in, but device list failed: {err}"
        else:
            self.message = "Wrong or expired code."

    def fetch(self, locate=True):
        if self.api.requires_2fa:
            self.status = "needs_2fa"
            self.message = "Apple session expired. New code needed."
            self.send_code()
            return
        manager = self.api.devices
        manager.refresh(locate=locate)
        devices, info = {}, {}
        for device in manager.devices.values():
            data = device.data
            dev_id = data["id"]
            name = data.get("name") or data.get("deviceDisplayName") or "Apple device"
            location = device.location
            if location is None and dev_id in self.info:
                location = self.info[dev_id].get("location")  # keep last known fix
            devices[dev_id] = name
            info[dev_id] = {
                "model": data.get("deviceDisplayName") or data.get("modelDisplayName"),
                "device_class": data.get("deviceClass") or "",
                "battery": data.get("batteryLevel"),
                "battery_status": data.get("batteryStatus"),
                "location": location,
            }
        self.devices, self.info = devices, info
        self.last_ok = time.time()
        self.message = ""

    def near_zone(self, zones):
        """Short note if a tracked device is inside/near a zone, else ''."""
        best = None
        for dev_id in self.selected:
            loc = (self.info.get(dev_id) or {}).get("location") or {}
            lat, lon = loc.get("latitude"), loc.get("longitude")
            if lat is None or lon is None:
                continue
            ts = loc.get("timeStamp")
            if ts and time.time() - float(ts) / 1000 > 1800:
                continue  # fix is 30+ min old (phone offline), fast polling would be pointless
            for z in zones:
                edge = distance_m(lat, lon, z["lat"], z["lon"]) - z["radius"]
                if edge <= self.near_distance and (best is None or edge < best[0]):
                    best = (edge, dev_id, z["name"])
        if not best:
            return ""
        name = self.names.get(best[1]) or self.devices.get(best[1], "Device")
        return f"{name} {'in' if best[0] <= 0 else 'near'} {best[2]}"

    def poll(self, zones=()):
        # Default to the slow interval first so a failed poll never hammers Apple
        self.next_poll = time.time() + self.interval * 60
        self.poll_note = ""
        try:
            self.fetch(locate=True)
        except Exception as err:  # noqa: BLE001
            self.message = f"Update failed: {err}"
            log.warning("%s: %s", self.username, self.message)
            return
        if self.fast_interval and zones:
            note = self.near_zone(zones)
            if note:
                self.next_poll = time.time() + self.fast_interval
                self.poll_note = note


def dev_key(acct, dev_id):
    return f"{acct.id}_{hashlib.sha1(dev_id.encode()).hexdigest()[:10]}"


class App:
    def __init__(self):
        self.mqtt = Mqtt()
        self.accounts = {}
        self.zones = []  # [{"name","lat","lon","radius"}] read from Home Assistant
        self.load()

    def load(self):
        if ACCOUNTS_FILE.exists():
            for cfg in json.loads(ACCOUNTS_FILE.read_text()):
                self.accounts[cfg["id"]] = Account(cfg)

    def save(self):
        DATA.mkdir(parents=True, exist_ok=True)
        tmp = ACCOUNTS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps([a.to_cfg() for a in self.accounts.values()], indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(ACCOUNTS_FILE)

    # ---- MQTT discovery / state ----
    def _topics(self, acct, dev_id):
        key = dev_key(acct, dev_id)
        return key, {
            "tracker_cfg": f"homeassistant/device_tracker/{PREFIX}_{key}/config",
            "battery_cfg": f"homeassistant/sensor/{PREFIX}_{key}_battery/config",
            "attrs": f"{PREFIX}/{key}/attributes",
            "battery": f"{PREFIX}/{key}/battery",
        }

    def publish_discovery(self, acct, dev_id):
        key, t = self._topics(acct, dev_id)
        info = acct.info.get(dev_id, {})
        device = {
            "identifiers": [f"{PREFIX}_{key}"],
            "name": acct.names.get(dev_id) or acct.devices.get(dev_id, "Apple device"),
            "manufacturer": "Apple",
            "model": info.get("model"),
        }
        self.mqtt.pub(
            t["tracker_cfg"],
            {
                "name": None,
                "unique_id": f"{PREFIX}_{key}_tracker",
                "json_attributes_topic": t["attrs"],
                "source_type": "gps",
                "availability_topic": STATUS_TOPIC,
                "icon": "mdi:cellphone",
                "device": device,
            },
        )
        self.mqtt.pub(
            t["battery_cfg"],
            {
                "name": "Battery",
                "unique_id": f"{PREFIX}_{key}_battery",
                "state_topic": t["battery"],
                "device_class": "battery",
                "unit_of_measurement": "%",
                "state_class": "measurement",
                "availability_topic": STATUS_TOPIC,
                "device": device,
            },
        )

    def publish_state(self, acct, dev_id):
        info = acct.info.get(dev_id)
        if not info:
            return
        _, t = self._topics(acct, dev_id)
        loc = info.get("location") or {}
        level = info.get("battery")
        if loc.get("latitude") is not None and loc.get("longitude") is not None:
            self.mqtt.pub(
                t["attrs"],
                {
                    "latitude": loc["latitude"],
                    "longitude": loc["longitude"],
                    "gps_accuracy": int(loc.get("horizontalAccuracy") or 0),
                    "battery_status": info.get("battery_status"),
                    "location_timestamp": loc.get("timeStamp"),
                },
            )
        if level is not None:
            self.mqtt.pub(t["battery"], str(int(level * 100)))

    def clear_device(self, acct, dev_id):
        _, t = self._topics(acct, dev_id)
        for topic in (t["tracker_cfg"], t["battery_cfg"], t["attrs"], t["battery"]):
            self.mqtt.pub(topic, "")
        acct.discovered.discard(dev_id)

    def sync_account(self, acct):
        """Make MQTT match the account's current picks. Safe to call any time."""
        if not self.mqtt.connected:
            return
        if acct.gen != self.mqtt.generation:
            acct.discovered.clear()  # broker reconnected: resend discovery
            acct.gen = self.mqtt.generation
        for dev_id in list(acct.discovered - set(acct.selected)):
            self.clear_device(acct, dev_id)
        for dev_id in acct.selected:
            if dev_id not in acct.devices:
                continue
            if dev_id not in acct.discovered:
                self.publish_discovery(acct, dev_id)
                acct.discovered.add(dev_id)
            self.publish_state(acct, dev_id)

    def remove_account(self, acct):
        for dev_id in list(acct.discovered):
            self.clear_device(acct, dev_id)
        self.accounts.pop(acct.id, None)
        self.save()

    # ---- background loop ----
    async def run_blocking(self, acct, fn, *args):
        async with acct.alock:
            await asyncio.to_thread(fn, *args)

    async def worker(self):
        while True:
            now = time.time()
            for acct in list(self.accounts.values()):
                try:
                    if acct.status in ("login", "error") and now >= acct.next_login:
                        if acct.status == "login" or acct.api is None:
                            await self.run_blocking(acct, acct.login)
                    elif acct.status == "ok" and now >= acct.next_poll:
                        await self.run_blocking(acct, acct.poll, self.zones)
                    self.sync_account(acct)
                except Exception:  # noqa: BLE001
                    log.exception("worker error for %s", acct.username)
            await asyncio.sleep(5)

    async def zone_refresher(self):
        """Read your Home Assistant zones every 5 minutes (needs homeassistant_api)."""
        token = os.getenv("SUPERVISOR_TOKEN")
        last_error = None
        while True:
            if token:
                try:
                    async with aiohttp.ClientSession() as session:
                        async with session.get(
                            "http://supervisor/core/api/states",
                            headers={"Authorization": f"Bearer {token}"},
                            timeout=aiohttp.ClientTimeout(total=30),
                        ) as resp:
                            if resp.status != 200:
                                raise RuntimeError(f"HTTP {resp.status}")
                            states = await resp.json()
                    zones = []
                    for st in states:
                        eid = st.get("entity_id", "")
                        attrs = st.get("attributes") or {}
                        if not eid.startswith("zone.") or attrs.get("passive"):
                            continue
                        if attrs.get("latitude") is None or attrs.get("longitude") is None:
                            continue
                        zones.append(
                            {
                                "name": attrs.get("friendly_name") or eid,
                                "lat": float(attrs["latitude"]),
                                "lon": float(attrs["longitude"]),
                                "radius": float(attrs.get("radius") or 100),
                            }
                        )
                    self.zones = zones
                    last_error = None
                    log.info("Loaded %d zone(s) from Home Assistant", len(zones))
                except Exception as err:  # noqa: BLE001
                    if str(err) != last_error:
                        log.warning("Couldn't read zones from Home Assistant: %s", err)
                        last_error = str(err)
            await asyncio.sleep(300)

    async def mqtt_connector(self):
        """Find broker details (manual options first, then the Supervisor) and connect."""
        opts = {}
        options_file = DATA / "options.json"
        if options_file.exists():
            opts = json.loads(options_file.read_text())
        while True:
            host, port = opts.get("mqtt_host") or "", opts.get("mqtt_port") or 1883
            user, password = opts.get("mqtt_username") or "", opts.get("mqtt_password") or ""
            if not host:
                token = os.getenv("SUPERVISOR_TOKEN")
                if token:
                    try:
                        async with aiohttp.ClientSession() as s:
                            async with s.get(
                                "http://supervisor/services/mqtt",
                                headers={"Authorization": f"Bearer {token}"},
                            ) as resp:
                                svc = (await resp.json()).get("data") or {}
                        host, port = svc.get("host"), svc.get("port", 1883)
                        user, password = svc.get("username", ""), svc.get("password", "")
                    except Exception as err:  # noqa: BLE001
                        log.warning("Couldn't read MQTT service from Supervisor: %s", err)
            if host:
                self.mqtt.start(host, port, user, password)
                return
            log.warning("No MQTT broker found. Install Mosquitto or set mqtt_host. Retrying in 30s.")
            await asyncio.sleep(30)


# ───────────────────────── Web UI (Ingress) ─────────────────────────
CSS = """
*{box-sizing:border-box}
body{font-family:-apple-system,system-ui,sans-serif;background:#111827;color:#e5e7eb;margin:0;padding:16px;max-width:680px;font-size:17px;line-height:1.4}
h1{font-size:1.5em;margin:0 0 4px}h3{margin:0 0 8px}
.card{background:#252b3b;border-radius:16px;padding:16px;margin:14px 0}
.muted{color:#9ca3af;font-size:.88em}.ok{color:#4ade80}.warn{color:#fbbf24}.bad{color:#f87171}
.tabs{display:flex;flex-wrap:wrap;gap:8px;margin:14px 0}
a.tab{flex:1 1 120px;text-align:center;padding:14px 10px;border-radius:12px;background:#394057;color:#e5e7eb;text-decoration:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
a.tab.active{background:#5b7fe8;color:#fff}
hr{border:0;border-top:1px solid #374151;margin:6px 0 14px}
input[type=text],input[type=password],input[type=number],select{width:100%;padding:12px;margin:4px 0 10px;border-radius:10px;border:1px solid #374151;background:#111827;color:#e5e7eb;font-size:1em}
button{padding:12px 18px;border:0;border-radius:10px;background:#5b7fe8;color:#fff;font-size:1em;margin:4px 8px 0 0}
button.grey{background:#394057}button.red{background:#b3261e}button.small{padding:8px 12px;font-size:.9em;margin:0}
.dev{background:#1e2433;border-radius:12px;padding:12px;margin:10px 0}
.devhead{display:flex;gap:10px;align-items:flex-start;justify-content:space-between;margin-bottom:6px}
.dev input{margin-bottom:0}.ico{font-size:1.4em}
.hidden-submit{position:absolute;left:-9999px;width:1px;height:1px;opacity:0}
"""


def esc(s):
    return html.escape(str(s))


def device_icon(info):
    """Pick an emoji from what Apple says the device is."""
    text = f"{info.get('device_class', '')} {info.get('model', '')}".lower()
    for needle, icon in (
        ("airpod", "\U0001F3A7"), ("beats", "\U0001F3A7"), ("airtag", "\U0001F3F7\uFE0F"),
        ("watch", "\u231A"), ("ipad", "\U0001F4F1"), ("iphone", "\U0001F4F1"),
        ("mac", "\U0001F4BB"), ("pod", "\U0001F3B5"), ("vision", "\U0001F97D"),
    ):
        if needle in text:
            return icon
    return "\U0001F4CD"


def ago(ts_ms):
    try:
        secs = max(0, time.time() - float(ts_ms) / 1000)
    except (TypeError, ValueError):
        return None
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        return f"{int(secs // 3600)} hr ago"
    return f"{int(secs // 86400)} days ago"


def describe(info):
    """e.g. 'iPhone 16 Pro Max · 85% · seen 3 min ago'"""
    bits = [info.get("model") or info.get("device_class") or "Apple device"]
    if info.get("battery") is not None:
        bits.append(f"{int(info['battery'] * 100)}%")
    loc = info.get("location") or {}
    seen = ago(loc.get("timeStamp"))
    bits.append(f"seen {seen}" if seen else "no location yet")
    return " \u00b7 ".join(bits)


def update_line(acct):
    wait = max(0, int(acct.next_poll - time.time()))
    line = f"Next update in {wait // 60}m {wait % 60}s"
    return f"{line} \u00b7 FAST: {acct.poll_note}" if acct.poll_note else line


def zone_line(zones):
    if not zones:
        return "Zones not loaded, so fast mode is off. Check the add-on log."
    names = ", ".join(z["name"] for z in zones[:6]) + ("..." if len(zones) > 6 else "")
    return f"Watching {len(zones)} zone(s): {names}"


def tab_label(acct):
    base = acct.label or acct.username.split("@")[0]
    return base if acct.status == "ok" else f"\u26a0\ufe0f {base}"


def render_account(acct, zones=()):
    cls = {"ok": "ok", "needs_2fa": "warn", "login": "warn", "error": "bad"}[acct.status]
    label = {
        "ok": "Connected",
        "needs_2fa": "Needs 2FA code",
        "login": "Logging in...",
        "error": "Error",
    }[acct.status]
    hidden = f"<input type='hidden' name='id' value='{esc(acct.id)}'>"
    out = [f"<div class='card'><h3>{esc(acct.username)}</h3><div class='{cls}'>{label}</div>"]
    if acct.message:
        out.append(f"<div class='muted'>{esc(acct.message)}</div>")
    if acct.status == "needs_2fa":
        out.append(
            f"<form method='post' action='code'>{hidden}"
            "<input type='text' name='code' inputmode='numeric' placeholder='6-digit code' autocomplete='off'>"
            "<button>Verify</button></form>"
            f"<form method='post' action='resend'>{hidden}<button class='grey'>Send a new code</button></form>"
        )
    elif acct.status == "error":
        out.append(f"<form method='post' action='retry'>{hidden}<button class='grey'>Retry login</button></form>")
    out.append("</div>")

    if acct.status == "ok":
        # --- add a device (dropdown) ---
        untracked = [(d, n) for d, n in acct.devices.items() if d not in acct.selected]
        untracked.sort(key=lambda x: x[1].lower())
        if untracked:
            options = "<option value=''>Pick a device...</option>" + "".join(
                f"<option value='{esc(d)}'>{device_icon(acct.info.get(d, {}))} {esc(n)} \u2014 "
                f"{esc(describe(acct.info.get(d, {})))}</option>"
                for d, n in untracked
            )
            add_body = (
                f"<form method='post' action='adddevice'>{hidden}<select name='device'>{options}</select>"
                "<input type='text' name='name' placeholder='Name in Home Assistant (optional)' autocomplete='off'>"
                "<button>Add device</button></form>"
            )
        elif acct.devices:
            add_body = "<div class='muted'>Every device on this account is already added.</div>"
        else:
            add_body = "<div class='muted'>No devices found on this account.</div>"
        out.append(f"<div class='card'><h3>Add a device</h3>{add_body}</div>")

        # --- tracked devices ---
        rows = []
        for d in acct.selected:
            info = acct.info.get(d, {})
            apple_name = acct.devices.get(d, "Unavailable device")
            rows.append(
                "<div class='dev'><div class='devhead'><div>"
                f"<span class='ico'>{device_icon(info)}</span> <b>{esc(apple_name)}</b>"
                f"<div class='muted'>{esc(describe(info)) if info else 'Not reported by Apple right now'}</div></div>"
                f"<button class='red small' formaction='removedevice' name='remove' value='{esc(d)}'>Remove</button></div>"
                f"<input type='text' name='name_{esc(d)}' value='{esc(acct.names.get(d, ''))}' "
                f"placeholder='Name in Home Assistant (blank = {esc(apple_name)})' autocomplete='off'></div>"
            )
        tracked = "".join(rows) or "<div class='muted'>Nothing added yet. Pick a device above.</div>"
        out.append(
            f"<div class='card'><h3>Tracked devices ({len(acct.selected)})</h3>"
            f"<div class='muted'>{esc(update_line(acct))}<br>{esc(zone_line(zones))}</div>"
            f"<form method='post' action='save'>{hidden}"
            "<button class='hidden-submit' tabindex='-1'>Save</button>"
            f"{tracked}"
            "<div class='muted' style='margin-top:12px'>Update every (minutes) when away from zones</div>"
            f"<input type='number' name='interval' min='1' max='60' value='{acct.interval}'>"
            "<div class='muted'>Fast updates near zones (seconds, 0 = off)</div>"
            f"<input type='number' name='fast_interval' min='0' max='300' value='{acct.fast_interval}'>"
            "<div class='muted'>Count as near a zone within (meters of its edge)</div>"
            f"<input type='number' name='near_distance' min='0' max='20000' value='{acct.near_distance}'>"
            "<div class='muted'>Tab name</div>"
            f"<input type='text' name='label' value='{esc(acct.label)}' placeholder='{esc(acct.username.split('@')[0])}'>"
            "<button>Save</button></form>"
            f"<form method='post' action='refresh'>{hidden}<button class='grey'>Update now</button></form>"
            "<div class='muted' style='margin-top:10px'>Names only change the display name. The entity ID stays as it "
            "was first created. To change it, use Settings, Entities.</div></div>"
        )

    out.append(
        "<div class='card'>"
        f"<form method='post' action='remove' onsubmit=\"return confirm('Remove this account and its entities?')\">{hidden}"
        "<button class='red'>Remove account</button></form></div>"
    )
    return "".join(out)


def render_add():
    return (
        "<div class='card'><h3>Add Apple ID</h3><form method='post' action='add'>"
        "<input type='text' name='username' placeholder='Apple ID email' autocapitalize='off' autocomplete='off'>"
        "<input type='password' name='password' placeholder='Password' autocomplete='off'>"
        "<input type='text' name='label' placeholder='Tab name (optional, like Jon or MJ)' autocomplete='off'>"
        "<button>Add account</button></form></div>"
    )


def render(app, sel=None):
    accounts = list(app.accounts.values())
    if sel == "new" or not accounts:
        active = "new"
    elif sel in app.accounts:
        active = sel
    else:
        active = accounts[0].id

    tabs = "".join(
        f"<a class='tab{' active' if a.id == active else ''}' href='?a={esc(a.id)}'>{esc(tab_label(a))}</a>"
        for a in accounts
    )
    tabs += f"<a class='tab{' active' if active == 'new' else ''}' href='?a=new'>+ Add</a>"
    content = render_add() if active == "new" else render_account(app.accounts[active], app.zones)
    mqtt_line = "MQTT: connected" if app.mqtt.connected else "MQTT: NOT connected (is Mosquitto running?)"
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>iCloud Lite</title><style>{CSS}</style></head><body>"
        f"<h1>iCloud Lite</h1><div class='muted'>{mqtt_line}</div>"
        f"<div class='tabs'>{tabs}</div><hr>{content}</body></html>"
    )


@web.middleware
async def ingress_only(request, handler):
    if request.remote not in INGRESS_IPS:
        return web.Response(status=403, text="Forbidden")
    return await handler(request)


def build_web(app_state):
    routes = web.RouteTableDef()

    def go(acct_id=None):
        return web.HTTPSeeOther(location=f"./?a={acct_id}" if acct_id else "./")

    async def get_acct(request):
        data = await request.post()
        return data, app_state.accounts.get(data.get("id", ""))

    def apply_form(acct, data):
        """Apply names / interval / tab name from the tracked-devices form."""
        for dev_id in acct.selected:
            key = f"name_{dev_id}"
            if key not in data:
                continue
            new_name = (data.get(key) or "").strip()
            if new_name != acct.names.get(dev_id, ""):
                if new_name:
                    acct.names[dev_id] = new_name
                else:
                    acct.names.pop(dev_id, None)
                acct.discovered.discard(dev_id)  # resend discovery with the new name
        if "interval" in data:
            try:
                acct.interval = max(1, min(60, int(data.get("interval", 5))))
            except ValueError:
                pass
        if "fast_interval" in data:
            try:
                value = int(data.get("fast_interval", 60))
                acct.fast_interval = 0 if value <= 0 else max(30, min(300, value))
            except ValueError:
                pass
        if "near_distance" in data:
            try:
                acct.near_distance = max(0, min(20000, int(data.get("near_distance", 1500))))
            except ValueError:
                pass
        if "label" in data:
            acct.label = (data.get("label") or "").strip()[:30]

    @routes.get("/")
    async def index(request):
        return web.Response(text=render(app_state, request.query.get("a")), content_type="text/html")

    @routes.post("/add")
    async def add(request):
        data = await request.post()
        username, password = data.get("username", "").strip(), data.get("password", "")
        if username and password and not any(
            a.username.lower() == username.lower() for a in app_state.accounts.values()
        ):
            acct = Account(
                {
                    "id": secrets.token_hex(4),
                    "username": username,
                    "password": password,
                    "label": (data.get("label") or "").strip()[:30],
                }
            )
            app_state.accounts[acct.id] = acct
            app_state.save()
            return go(acct.id)
        return go("new")

    @routes.post("/code")
    async def code(request):
        data, acct = await get_acct(request)
        if acct and acct.api:
            await app_state.run_blocking(acct, acct.verify, data.get("code", ""))
        return go(acct.id if acct else None)

    @routes.post("/resend")
    async def resend(request):
        _, acct = await get_acct(request)
        if acct and acct.api:
            await app_state.run_blocking(acct, acct.send_code)
        return go(acct.id if acct else None)

    @routes.post("/adddevice")
    async def adddevice(request):
        data, acct = await get_acct(request)
        if acct:
            dev_id = data.get("device", "")
            if dev_id and dev_id in acct.devices and dev_id not in acct.selected:
                acct.selected.append(dev_id)
                name = (data.get("name") or "").strip()
                if name:
                    acct.names[dev_id] = name
                acct.discovered.discard(dev_id)
                acct.next_poll = 0
                app_state.save()
                app_state.sync_account(acct)
        return go(acct.id if acct else None)

    @routes.post("/removedevice")
    async def removedevice(request):
        data, acct = await get_acct(request)
        if acct:
            apply_form(acct, data)
            dev_id = data.get("remove", "")
            if dev_id in acct.selected:
                acct.selected.remove(dev_id)
            app_state.save()
            app_state.sync_account(acct)  # clears the removed device's entities
        return go(acct.id if acct else None)

    @routes.post("/save")
    async def save(request):
        data, acct = await get_acct(request)
        if acct:
            apply_form(acct, data)
            acct.next_poll = 0  # poll right away
            app_state.save()
            app_state.sync_account(acct)
        return go(acct.id if acct else None)

    @routes.post("/refresh")
    async def refresh(request):
        _, acct = await get_acct(request)
        if acct:
            acct.next_poll = 0
        return go(acct.id if acct else None)

    @routes.post("/retry")
    async def retry(request):
        _, acct = await get_acct(request)
        if acct:
            acct.status, acct.api, acct.next_login = "login", None, 0
        return go(acct.id if acct else None)

    @routes.post("/remove")
    async def remove(request):
        _, acct = await get_acct(request)
        if acct:
            app_state.remove_account(acct)
        return go()

    web_app = web.Application(middlewares=[ingress_only])
    web_app.add_routes(routes)
    return web_app


async def main():
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    state = App()
    web_app = build_web(state)
    runner = web.AppRunner(web_app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8099).start()
    log.info("Web UI up on :8099 with %d saved account(s)", len(state.accounts))
    await asyncio.gather(state.mqtt_connector(), state.worker(), state.zone_refresher())


if __name__ == "__main__":
    asyncio.run(main())
