"""iCloud Lite add-on: track Apple devices from multiple iCloud accounts, publish via MQTT."""
import asyncio
import hashlib
import html
import json
import logging
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


# ──────────────────────── Accounts ────────────────────────
class Account:
    def __init__(self, cfg):
        self.id = cfg["id"]
        self.username = cfg["username"]
        self.password = cfg["password"]
        self.interval = int(cfg.get("interval", 5))
        self.selected = list(cfg.get("devices", []))
        self.names = dict(cfg.get("names", {}))  # device_id -> custom name for HA
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
            "devices": self.selected,
            "names": self.names,
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

    def poll(self):
        self.next_poll = time.time() + self.interval * 60
        try:
            self.fetch(locate=True)
        except Exception as err:  # noqa: BLE001
            self.message = f"Update failed: {err}"
            log.warning("%s: %s", self.username, self.message)


def dev_key(acct, dev_id):
    return f"{acct.id}_{hashlib.sha1(dev_id.encode()).hexdigest()[:10]}"


class App:
    def __init__(self):
        self.mqtt = Mqtt()
        self.accounts = {}
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
                        await self.run_blocking(acct, acct.poll)
                    self.sync_account(acct)
                except Exception:  # noqa: BLE001
                    log.exception("worker error for %s", acct.username)
            await asyncio.sleep(5)

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
body{font-family:-apple-system,system-ui,sans-serif;background:#111;color:#eee;margin:0;padding:16px;max-width:640px}
h1{font-size:1.3em}.card{background:#1c1c24;border-radius:12px;padding:14px;margin:12px 0}
.ok{color:#4caf50}.warn{color:#ffb300}.bad{color:#ef5350}.muted{color:#999;font-size:.85em}
input[type=text],input[type=password],input[type=number]{width:100%;box-sizing:border-box;padding:10px;margin:4px 0 8px;border-radius:8px;border:1px solid #333;background:#0d0d0d;color:#eee;font-size:1em}
button{padding:10px 14px;border:0;border-radius:8px;background:#3b82f6;color:#fff;font-size:1em;margin:4px 4px 0 0}
button.red{background:#b3261e}button.grey{background:#444}label.dev{display:flex;align-items:center;gap:10px;padding:8px 0}.devrow{border-bottom:1px solid #2a2a33;padding-bottom:6px}.nm{margin:0 0 4px 0!important;font-size:.9em!important}label.dev input{width:20px;height:20px}.ico{font-size:1.5em}.sub{margin-top:2px}
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


def render(app):
    parts = []
    for acct in app.accounts.values():
        cls = {"ok": "ok", "needs_2fa": "warn", "login": "warn", "error": "bad"}[acct.status]
        label = {
            "ok": "Connected",
            "needs_2fa": "Needs 2FA code",
            "login": "Logging in...",
            "error": "Error",
        }[acct.status]
        body = [f"<h3>{esc(acct.username)}</h3>",
                f"<div class='{cls}'>{label}</div>"]
        if acct.message:
            body.append(f"<div class='muted'>{esc(acct.message)}</div>")
        hidden = f"<input type='hidden' name='id' value='{esc(acct.id)}'>"
        if acct.status == "needs_2fa":
            body.append(
                f"<form method='post' action='code'>{hidden}"
                "<input type='text' name='code' inputmode='numeric' placeholder='6-digit code' autocomplete='off'>"
                "<button>Verify</button></form>"
                f"<form method='post' action='resend'>{hidden}<button class='grey'>Send a new code</button></form>"
            )
        elif acct.status == "ok":
            rows = []
            for d, n in sorted(acct.devices.items(), key=lambda x: x[1].lower()):
                info = acct.info.get(d, {})
                sub = f"<div class='muted sub'>{esc(describe(info))}</div>"
                custom = acct.names.get(d, "")
                rows.append(
                    "<div class='devrow'>"
                    f"<label class='dev'><input type='checkbox' name='devices' value='{esc(d)}'"
                    f"{' checked' if d in acct.selected else ''}>"
                    f"<span class='ico'>{device_icon(info)}</span>"
                    f"<span><b>{esc(n)}</b>{sub}</span></label>"
                    f"<input class='nm' type='text' name='name_{esc(d)}' value='{esc(custom)}' "
                    f"placeholder='Name in Home Assistant (blank = {esc(n)})' autocomplete='off'>"
                    "</div>"
                )
            boxes = "".join(rows) or "<div class='muted'>No devices found.</div>"
            body.append(
                f"<form method='post' action='save'>{hidden}<div class='muted'>Devices to track (optional: type the name you want in Home Assistant)</div>{boxes}"
                f"<div class='muted'>Update every (minutes)</div>"
                f"<input type='number' name='interval' min='1' max='60' value='{acct.interval}'>"
                "<button>Save</button></form>"
                f"<form method='post' action='refresh'>{hidden}<button class='grey'>Update now</button></form>"
            )
        elif acct.status == "error":
            body.append(f"<form method='post' action='retry'>{hidden}<button class='grey'>Retry login</button></form>")
        body.append(
            f"<form method='post' action='remove' onsubmit=\"return confirm('Remove this account?')\">{hidden}"
            "<button class='red'>Remove account</button></form>"
        )
        parts.append(f"<div class='card'>{''.join(body)}</div>")

    mqtt_line = "MQTT: connected" if app.mqtt.connected else "MQTT: NOT connected (is Mosquitto running?)"
    parts.append(
        "<div class='card'><h3>Add Apple ID</h3><form method='post' action='add'>"
        "<input type='text' name='username' placeholder='Apple ID email' autocapitalize='off' autocomplete='off'>"
        "<input type='password' name='password' placeholder='Password' autocomplete='off'>"
        "<button>Add account</button></form></div>"
    )
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>iCloud Lite</title><style>{CSS}</style></head><body>"
        f"<h1>iCloud Lite</h1><div class='muted'>{mqtt_line}</div>{''.join(parts)}</body></html>"
    )


@web.middleware
async def ingress_only(request, handler):
    if request.remote not in INGRESS_IPS:
        return web.Response(status=403, text="Forbidden")
    return await handler(request)


def build_web(app_state):
    routes = web.RouteTableDef()

    def done():
        return web.HTTPSeeOther(location="./")

    async def get_acct(request):
        data = await request.post()
        return data, app_state.accounts.get(data.get("id", ""))

    @routes.get("/")
    async def index(request):
        return web.Response(text=render(app_state), content_type="text/html")

    @routes.post("/add")
    async def add(request):
        data = await request.post()
        username, password = data.get("username", "").strip(), data.get("password", "")
        if username and password and not any(
            a.username.lower() == username.lower() for a in app_state.accounts.values()
        ):
            acct = Account({"id": secrets.token_hex(4), "username": username, "password": password})
            app_state.accounts[acct.id] = acct
            app_state.save()
        return done()

    @routes.post("/code")
    async def code(request):
        data, acct = await get_acct(request)
        if acct and acct.api:
            await app_state.run_blocking(acct, acct.verify, data.get("code", ""))
        return done()

    @routes.post("/resend")
    async def resend(request):
        _, acct = await get_acct(request)
        if acct and acct.api:
            await app_state.run_blocking(acct, acct.send_code)
        return done()

    @routes.post("/save")
    async def save(request):
        data, acct = await get_acct(request)
        if acct:
            acct.selected = data.getall("devices", [])
            for dev_id in list(acct.devices):
                new_name = (data.get(f"name_{dev_id}") or "").strip()
                if new_name != acct.names.get(dev_id, ""):
                    if new_name:
                        acct.names[dev_id] = new_name
                    else:
                        acct.names.pop(dev_id, None)
                    acct.discovered.discard(dev_id)  # resend discovery with the new name
            try:
                acct.interval = max(1, min(60, int(data.get("interval", 5))))
            except ValueError:
                pass
            acct.next_poll = 0  # poll right away
            app_state.save()
            app_state.sync_account(acct)
        return done()

    @routes.post("/refresh")
    async def refresh(request):
        _, acct = await get_acct(request)
        if acct:
            acct.next_poll = 0
        return done()

    @routes.post("/retry")
    async def retry(request):
        _, acct = await get_acct(request)
        if acct:
            acct.status, acct.api, acct.next_login = "login", None, 0
        return done()

    @routes.post("/remove")
    async def remove(request):
        _, acct = await get_acct(request)
        if acct:
            app_state.remove_account(acct)
        return done()

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
    await asyncio.gather(state.mqtt_connector(), state.worker())


if __name__ == "__main__":
    asyncio.run(main())
