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
from pyicloud.exceptions import (
    PyiCloud2FARequiredException,
    PyiCloud2SARequiredException,
    PyiCloudFailedLoginException,
)

DATA = Path(os.getenv("DATA_DIR", "/data"))
ACCOUNTS_FILE = DATA / "accounts.json"
COOKIES = DATA / "cookies"
PREFIX = "icloud_lite"
STATUS_TOPIC = f"{PREFIX}/status"
INGRESS_IPS = {"172.30.32.2", "127.0.0.1", "::1"}
LOGIN_RETRY_SECONDS = 1800  # never hammer Apple after a failed login
AUTH_ERRORS = (PyiCloudFailedLoginException, PyiCloud2FARequiredException, PyiCloud2SARequiredException)

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
        self.last_relogin = 0.0
        self.throttle_count = 0  # consecutive Apple 503/429 refusals
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

    @property
    def tag(self):
        """Short name for log lines (never the full email)."""
        return self.label or self.username.split("@")[0] or "account"

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
        log.info("%s: logging in", self.tag)
        try:
            self.api = PyiCloudService(
                self.username, self.password, cookie_directory=str(COOKIES), with_family=True,
                # iCloud Lite refreshes on its own schedule; stop pyicloud polling Apple in the background too
                refresh_interval=None,
            )
            if self.api.requires_2fa:
                self.status = "needs_2fa"
                self.message = "Apple needs a verification code."
                log.info("%s: Apple wants a 2FA code, asking Apple to send one", self.tag)
                self.send_code()
                return
            self.status = "ok"
            self.message = ""
            self.throttle_count = 0
            self.fetch(locate=False)
            log.info("%s: logged in, %d device(s) on the account", self.tag, len(self.devices))
        except Exception as err:  # noqa: BLE001
            self.status = "error"
            text = str(err)
            if any(k in text for k in ("503", "429", "Service Temporarily Unavailable", "Too Many")):
                # Apple is throttling logins from this connection. Back off (1h, 2h, 4h, then 6h)
                # because retrying sooner just extends the block.
                self.throttle_count += 1
                wait = min(6 * 3600, 3600 * 2 ** (self.throttle_count - 1))
                self.next_login = time.time() + wait
                self.message = (
                    f"Apple is temporarily refusing logins (error 503). Trying again automatically in "
                    f"{wait // 3600} hr. Tapping Retry makes the block last longer."
                )
            else:
                self.throttle_count = 0
                self.message = f"Login failed: {text[:200]}"
            log.warning("%s: %s", self.tag, self.message)

    def send_code(self):
        try:
            self.api.request_2fa_code()
        except Exception as err:  # noqa: BLE001
            log.warning("%s: couldn't request 2FA code: %s", self.tag, err)

    def verify(self, code):
        try:
            ok = self.api.validate_2fa_code(code.strip())
            if ok and not self.api.is_trusted_session:
                self.api.trust_session()
        except Exception as err:  # noqa: BLE001
            self.message = f"Code check failed: {err}"
            log.warning("%s: 2FA code check failed: %s", self.tag, err)
            return
        if ok:
            log.info("%s: 2FA code accepted", self.tag)
            self.status = "ok"
            self.message = ""
            try:
                self.fetch(locate=False)
            except Exception as err:  # noqa: BLE001
                self.message = f"Logged in, but device list failed: {err}"
        else:
            log.warning("%s: 2FA code rejected by Apple", self.tag)
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
        log.debug("%s: fetched %d device(s) (locate=%s)", self.tag, len(devices), locate)

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
            log.debug("%s: no tracked device is near any zone", self.tag)
            return ""
        name = self.names.get(best[1]) or self.devices.get(best[1], "Device")
        log.debug("%s: closest zone edge %.0f m (%s)", self.tag, best[0], best[2])
        return f"{name} {'in' if best[0] <= 0 else 'near'} {best[2]}"

    def poll(self, zones=()):
        # Default to the slow interval first so a failed poll never hammers Apple
        self.next_poll = time.time() + self.interval * 60
        prev_note, self.poll_note = self.poll_note, ""
        try:
            self.fetch(locate=True)
        except Exception as err:  # noqa: BLE001
            self.message = f"Update failed: {err}"
            log.warning("%s: %s", self.tag, self.message)
            if isinstance(err, AUTH_ERRORS) or "password" in str(err).lower():
                # Apple dropped our session. Log in again (asks for a 2FA code if needed),
                # but only once per 30 min so we never hammer Apple.
                if time.time() - self.last_relogin > LOGIN_RETRY_SECONDS:
                    self.last_relogin = time.time()
                    self.status, self.api, self.next_login = "login", None, 0
                else:
                    self.status = "error"
                    self.message += " Apple keeps rejecting this login. Tap Retry login."
            return
        if self.fast_interval and zones:
            note = self.near_zone(zones)
            if note:
                self.next_poll = time.time() + self.fast_interval
                self.poll_note = note
        if self.poll_note and not prev_note:
            log.info("%s: FAST mode on (%s), polling every %ss", self.tag, self.poll_note, self.fast_interval)
        elif prev_note and not self.poll_note:
            log.info("%s: fast mode off, back to every %s min", self.tag, self.interval)
        log.debug("%s: poll ok, next in %ds", self.tag, round(self.next_poll - time.time()))


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
        log.info("MQTT discovery sent for %s", device["name"])
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
        log.debug("MQTT state %s: lat=%s lon=%s battery=%s", _[:24], loc.get("latitude"), loc.get("longitude"), level)
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
        log.info("MQTT entities removed for %s", acct.names.get(dev_id) or acct.devices.get(dev_id, dev_id[:8]))
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
                    log.exception("worker error for %s", acct.tag)
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
# Web UI follows the Home Assistant theme. Kept in sync by .shared/sync_theme.py.
HA_THEME = r"""<!-- ha-theme v1.3.0: copied from .shared/ha-theme.js, edit it there -->
<script>
window.__hbAddon = "icloud_lite";
/* HA Theme Bridge v1.3.0
 * Makes an add-on web UI follow the active Home Assistant theme (colors, dark/light,
 * dashboard wallpaper, glass blur, card corners and shadows) and updates live when
 * the theme changes. It reads the theme from the Home Assistant page that holds the
 * add-on (ingress runs on the same origin) and remaps this page's own colors to it.
 * Opened outside Home Assistant it does nothing, so the page keeps its own look.
 * Wallpaper, first match wins: the add-on's own "wallpaper" option (Configuration tab), then the
 * shared add-on wallpaper picked in Photo Hub (/local/addon-wallpaper/wallpaper.json), then the theme's.
 * The add-on option:
 *   empty = use the theme's wallpaper, "none" = no wallpaper, or an image:
 *   /local/pic.jpg (= /config/www/pic.jpg), just pic.jpg, /config/www/..., or https://...
 * Readability: over a wallpaper it measures the picture's bright and dark areas and dims (dark
 * themes) or lightens (light themes) it just enough for text to reach a 4.5:1 contrast.
 * Opt out on a page: <html data-ha-theme-off>
 * Variables you can use in new pages: --hb-bg --hb-card --hb-text --hb-text2 --hb-line
 * --hb-primary --hb-accent --hb-on --hb-error --hb-warning --hb-success --hb-field,
 * plus every core HA variable (--primary-color, --card-background-color, ...).
 */
(function () {
  'use strict';
  if (window.__haThemeBridge) return;
  window.__haThemeBridge = 1;
  var doc = document, root = doc.documentElement;
  if (root.hasAttribute('data-ha-theme-off')) return;

  /* ---------- find the Home Assistant window above us ---------- */
  var HA = null;
  try {
    var w = window;
    while (w.parent && w.parent !== w) {
      w = w.parent;
      if (w.document && w.document.querySelector('home-assistant')) HA = w;
    }
  } catch (e) { /* cross-origin parent: stop climbing */ }
  if (!HA) return;
  var nested = window.parent !== HA;

  /* ---------- color helpers ---------- */
  function parse(c) {
    if (!c) return null;
    c = String(c).trim().toLowerCase();
    var m;
    if (c.charAt(0) === '#') {
      var h = c.slice(1);
      if (!/^[0-9a-f]+$/.test(h)) return null;
      if (h.length === 3 || h.length === 4) h = h.replace(/./g, '$&$&');
      if (h.length !== 6 && h.length !== 8) return null;
      return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16),
        h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1];
    }
    if ((m = c.match(/^rgba?\(([^)]+)\)$/))) {
      var p = m[1].split(/[\s,\/]+/).filter(Boolean);
      if (p.length < 3) return null;
      var f = function (v, alpha) {
        return /%$/.test(v) ? parseFloat(v) * (alpha ? 0.01 : 2.55) : parseFloat(v);
      };
      var out = [f(p[0]), f(p[1]), f(p[2]), p.length > 3 ? f(p[3], 1) : 1];
      for (var i = 0; i < 4; i++) if (isNaN(out[i])) return null;
      return out;
    }
    if (c === 'white') return [255, 255, 255, 1];
    if (c === 'black') return [0, 0, 0, 1];
    if (c === 'transparent') return [0, 0, 0, 0];
    return null;
  }
  function info(c) {
    var r = c[0] / 255, g = c[1] / 255, b = c[2] / 255;
    var mx = Math.max(r, g, b), mn = Math.min(r, g, b), ch = mx - mn, h = 0;
    if (ch) {
      if (mx === r) h = ((g - b) / ch) % 6;
      else if (mx === g) h = (b - r) / ch + 2;
      else h = (r - g) / ch + 4;
      h *= 60;
      if (h < 0) h += 360;
    }
    return { l: (mx + mn) / 2, ch: ch, h: h, a: c[3] };
  }
  /* greys, plus the dark navy/indigo shades many dark UIs use as their "grey" */
  function isNeutral(i) {
    return i.ch < 0.12 || (i.ch < 0.2 && i.h >= 200 && i.h <= 290 && (i.l < 0.32 || i.l > 0.85));
  }
  function lum(c) { return c ? (0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]) / 255 : 0; }
  function rgbStr(c) { return Math.round(c[0]) + ',' + Math.round(c[1]) + ',' + Math.round(c[2]); }
  function hueRole(h) {
    return (h < 15 || h >= 335) ? 'error' : h < 65 ? 'warning' : h < 170 ? 'success' : 'primary';
  }
  function tint(role, a) { return 'rgba(var(--hb-' + role + '-rgb),' + (Math.round(a * 1000) / 1000) + ')'; }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }

  var probe = null;
  function toRGB(v) {
    v = (v || '').trim();
    if (!v) return null;
    var p = parse(v);
    if (p) return p;
    if (!probe) {
      probe = doc.createElement('i');
      probe.style.display = 'none';
      (doc.body || root).appendChild(probe);
    }
    probe.style.color = '';
    probe.style.color = v;
    if (!probe.style.color) return null;
    return parse(getComputedStyle(probe).color);
  }

  /* ---------- what the page looked like before we touched it ---------- */
  var REFS = { dark: { b: 0.08, t: 0.92 }, light: { b: 0.96, t: 0.12 } };
  var designScheme = 'dark';
  (function measure() {
    var el = doc.body || root, cs = getComputedStyle(el);
    var txt = parse(cs.color), bg = parse(cs.backgroundColor);
    if (!bg || bg[3] < 0.5) bg = parse(getComputedStyle(root).backgroundColor);
    if (txt) designScheme = info(txt).l > 0.5 ? 'dark' : 'light';
    else if (bg && bg[3] > 0.5) designScheme = info(bg).l < 0.5 ? 'dark' : 'light';
    var ref = REFS[designScheme];
    if (txt) ref.t = info(txt).l;
    if (bg && bg[3] > 0.5 && Math.abs(info(bg).l - ref.t) > 0.3) ref.b = info(bg).l;
  })();

  /* ---------- color rewriting rules ---------- */
  var COLOR_RE = /#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)|\b(?:white|black)\b/g;
  var cardVars = {}, solidVars = {}, pageVars = {};

  function lastCompound(sel) {
    return (sel || '').split(',').map(function (s) {
      var parts = s.trim().split(/\s*[\s>+~]\s*/);
      return parts[parts.length - 1] || '';
    });
  }
  function kindOf(sel) {
    var lasts = lastCompound(sel), k = '';
    for (var i = 0; i < lasts.length; i++) {
      var s = lasts[i].toLowerCase();
      if (/^(html|body|:root)\b/.test(s)) return 'page';
      if (/\.(overlay|backdrop|scrim|mask|shade|sheet|modal|lightbox)\b|::backdrop/.test(s)) return 'scrim';
      if (/^(input|select|textarea)\b|\.(input|field-input|textfield)\b/.test(s)) k = k || 'input';
      else if (/^(header|nav|footer)\b|\.(top|topbar|nav|navbar|header|footer|bar|toolbar|appbar|bottom|tabbar|savebar)\b/.test(s)) k = k || 'bar';
      else if (/\.(card|panel|surface|sheet|modal|dialog|popup|menu|toast|drawer|pane|tile)\b|^(dialog|details)\b/.test(s)) k = k || 'card';
    }
    return k;
  }
  function ctxOf(p) {
    if (/^background(-color|-image)?$/.test(p)) return 'bg';
    if (p === 'color' || p === 'caret-color' || p === '-webkit-text-fill-color' || p === 'text-decoration-color') return 'text';
    if (/^border(-(top|right|bottom|left|block|inline)(-(start|end))?)?-color$/.test(p) || p === 'outline-color' || p === 'column-rule-color') return 'line';
    if (p === 'accent-color') return 'accent';
    return '';
  }

  /* returns {v, solid, card} or null to leave the color alone */
  function mapColor(c, ctx, ref, kind) {
    var i = info(c), a = i.a, dark = ref.b < 0.5;
    if (a === 0) return null;
    var span = ref.t - ref.b, t = span ? (i.l - ref.b) / span : 0, at = Math.abs(t);
    var neutral = isNeutral(i) || (ctx === 'line' && i.ch < 0.26 && (dark ? i.l < 0.45 : i.l > 0.6));
    if (neutral) {
      if (a < 0.98) {
        if (t > 0.5) return { v: tint('text', a) };            /* light-on-dark wash -> text tint */
        if (ctx !== 'bg' || kind === 'scrim') return null;     /* overlays and shadows stay */
        if (i.l < 0.05 && a < 0.5) return { v: 'var(--hb-inset)' };  /* black wash = inset box */
        if (i.l < 0.05) return null;
        if (kind === 'bar' || a > 0.8) return { v: 'var(--hb-bar)', card: true };
        if (kind === 'card' || a > 0.4) return { v: 'var(--hb-card)', card: true };
        return { v: 'var(--hb-inset)' };
      }
      if (ctx === 'text') return { v: t > 0.72 ? 'var(--hb-text)' : 'var(--hb-text2)' };
      if (ctx === 'line') return { v: 'var(--hb-line)' };
      if (ctx === 'accent') return { v: 'var(--hb-primary)' };
      if (kind === 'page') return { v: 'var(--hb-bg)' };
      if (kind === 'input') return { v: 'var(--hb-field)' };
      if (kind === 'bar') return { v: 'var(--hb-bar)', card: true };
      if (kind === 'card' && t < 0.45) return { v: 'var(--hb-card)', card: true };
      if (at < 0.04) return { v: 'var(--hb-inset)' };
      if (t > 0.6) return null;                                 /* bright chip on dark page: leave */
      return { v: tint('text', clamp(0.03 + at * 0.4, 0.05, 0.16)) };
    }
    var role = hueRole(i.h);
    if (a < 0.98) return { v: tint(role, a) };
    if (ctx === 'bg') {
      if (dark ? i.l < 0.3 : i.l > 0.82) return { v: tint(role, 0.2) };   /* tinted note/chip bg */
      return { v: 'var(--hb-' + role + ')', solid: true };
    }
    return { v: 'var(--hb-' + role + ')' };
  }

  var SEM_NAMES = [
    [/^(ok|good|success|live|green|pos|positive)(-?\d)?$/, 'success'],
    [/^(bad|red|danger|err|error|neg|negative)(-?\d)?$/, 'error'],
    [/^(warn|warning|amber)(-?\d)?$/, 'warning'],
    [/^(acc|accent|ac|primary|brand|link)$/, 'primary'],
    [/^(acc|accent|ac|primary)-?2$/, 'accent']
  ];
  function mapVar(name, val, ref) {
    var n = name.slice(2).toLowerCase();
    if (/^hb-/.test(n)) return null;
    var c = parse(val);
    if (!c) return null;
    var i = info(c), neutral = isNeutral(i), dark = ref.b < 0.5;
    var span = ref.t - ref.b, t = span ? (i.l - ref.b) / span : 0, at = Math.abs(t);
    if (n === 'on' || /^(acc|accent|ac|primary)-?(ink|on|fg|text)$|^on-(acc|accent|primary)$/.test(n)) return { v: 'var(--hb-on)' };
    var soft = /(-|^)(soft|tint|wash|bg|bg2|weak)$|soft$/.test(n), base = n.replace(/-?(soft|tint|wash|bg|bg2|weak|ink)$|soft$/, '');
    for (var k = 0; k < SEM_NAMES.length; k++) {
      if (SEM_NAMES[k][0].test(base) && (!neutral || base !== n)) {
        var role = SEM_NAMES[k][1];
        if (/-ink$/.test(n)) return { v: 'var(--hb-text)' };
        if (soft || i.a < 0.98) return { v: tint(role === 'accent' ? 'primary' : role, i.a < 0.98 ? i.a : 0.16) };
        return { v: 'var(--hb-' + role + ')', solid: true };
      }
    }
    if (/-ink$/.test(n)) return { v: 'var(--hb-text)' };
    if (!neutral) return null;                                 /* unknown colorful var (state colors): leave */
    if (i.a < 0.98) return t > 0.5 ? { v: tint('text', i.a) } : null;
    if (/line|border|sep|divid|rule|stroke|outline/.test(n)) return { v: 'var(--hb-line)' };
    if (/^(mut|muted|dim|mu|sub|sec|secondary|faint|hint|txt2|text2|tx2|ink2|subtle)(-?\d)?$/.test(n)) return { v: 'var(--hb-text2)' };
    if (/^(text|txt|tx|fg|fore|ink|c|font-color|text-color)(-?\d)?$/.test(n) && t > 0.3) return { v: t > 0.72 ? 'var(--hb-text)' : 'var(--hb-text2)' };
    if (/field|input|code|well/.test(n)) return { v: 'var(--hb-field)' };
    if (/chip|card-?2|panel-?2|surface-?2|bg-?3|raised|hover|alt|elev/.test(n)) return { v: tint('text', dark ? 0.08 : 0.06) };
    if (/card|panel|surface|sheet|tile|box|pane/.test(n)) return { v: 'var(--hb-card)', card: true };
    if (/^(bg|bg-?[0-2]|background|base|page|canvas|app-bg|ink)$/.test(n) || at < 0.04) return { v: 'var(--hb-bg)' };
    if (t > 0.72) return { v: 'var(--hb-text)' };
    if (t > 0.4) return { v: 'var(--hb-text2)' };
    return { v: tint('text', clamp(0.03 + at * 0.4, 0.05, 0.14)) };
  }

  function refVarNames(v) {
    var out = [], re = /var\(\s*(--[\w-]+)/g, m;
    while ((m = re.exec(v || ''))) out.push(m[1]);
    return out;
  }

  function doStyle(st, sel, scheme) {
    var ref = REFS[scheme], kind = kindOf(sel), names = [], k;
    for (k = 0; k < st.length; k++) names.push(st[k]);
    var solidBg = false, isCard = false;
    names.forEach(function (p) {
      var v = st.getPropertyValue(p), pr = st.getPropertyPriority(p);
      if (p.indexOf('--') === 0) {
        var r = mapVar(p, v, ref);
        pageVars[p] = 1;
        if (r) {
          if (r.card) cardVars[p] = 1;
          if (r.solid) solidVars[p] = 1;
          st.setProperty(p, r.v, pr);
        }
        return;
      }
      var ctx = ctxOf(p);
      if (!ctx || !v) return;
      var nv = v.replace(COLOR_RE, function (tok) {
        var c = parse(tok);
        if (!c) return tok;
        var r = mapColor(c, ctx, ref, kind);
        if (!r) return tok;
        if (ctx === 'bg' && r.solid) solidBg = true;
        if (ctx === 'bg' && r.card) isCard = true;
        return r.v;
      });
      if (nv !== v) st.setProperty(p, nv, pr);
    });
    /* shorthands that mix var() with literal colors only show up on the shorthand itself */
    ['background', 'border', 'border-top', 'border-right', 'border-bottom', 'border-left', 'outline'].forEach(function (p) {
      var v = st.getPropertyValue(p);
      if (!v || v.indexOf('var(') < 0) return;
      var ctx = p === 'background' ? 'bg' : 'line', pr = st.getPropertyPriority(p);
      var nv = v.replace(COLOR_RE, function (tok) {
        var c = parse(tok), r = c && mapColor(c, ctx, REFS[scheme], kind);
        if (!r) return tok;
        if (ctx === 'bg' && r.card) isCard = true;
        return r.v;
      });
      if (nv !== v) st.setProperty(p, nv, pr);
    });
    /* backgrounds written as var(--card) / var(--accent) */
    ['background', 'background-color', 'background-image'].forEach(function (p) {
      refVarNames(st.getPropertyValue(p)).forEach(function (n) {
        if (cardVars[n]) isCard = true;
        if (solidVars[n]) solidBg = true;
      });
    });
    if (solidBg) {
      var col = st.getPropertyValue('color');
      if (!col || /var\(--hb-text2?\)/.test(col) || refVarNames(col).some(function (n) {
        return /^--(text|txt|tx|ink|fg|c)$/.test(n);
      })) st.setProperty('color', 'var(--hb-on)');
    }
    if (isCard && kind !== 'page') {
      st.setProperty('-webkit-backdrop-filter', 'var(--hb-blur)');
      st.setProperty('backdrop-filter', 'var(--hb-blur)');
      ['top-left', 'top-right', 'bottom-right', 'bottom-left'].forEach(function (c) {
        var p = 'border-' + c + '-radius', v = st.getPropertyValue(p);
        if (v && v.indexOf('--hb-radius') < 0) st.setProperty(p, 'var(--hb-radius,' + v + ')');
      });
      var sh = st.getPropertyValue('box-shadow');
      if (sh.indexOf('--hb-shadow') < 0) st.setProperty('box-shadow', 'var(--hb-shadow,' + (sh || 'none') + ')');
      ['top', 'right', 'bottom', 'left'].forEach(function (s) {
        var p = 'border-' + s + '-color', v = st.getPropertyValue(p);
        if (v === 'var(--hb-line)') st.setProperty(p, 'var(--hb-card-border,var(--hb-line))');
        var pw = 'border-' + s + '-width', w = st.getPropertyValue(pw);
        if (w && w.indexOf('--hb-') < 0) st.setProperty(pw, 'var(--hb-card-border-width,' + w + ')');
      });
    }
  }

  function schemeOfMedia(text, fallback) {
    var m = /prefers-color-scheme\s*:\s*(dark|light)/.exec(text || '');
    return m ? m[1] : fallback;
  }
  function walk(rules, scheme) {
    for (var i = 0; i < rules.length; i++) {
      var r = rules[i];
      if (r.style && r.selectorText != null) {
        doStyle(r.style, r.selectorText, scheme);
        if (r.cssRules && r.cssRules.length) walk(r.cssRules, scheme);
      } else if (r.cssRules && !(r.type === 7)) {           /* media / supports / layer / container */
        walk(r.cssRules, r.media ? schemeOfMedia(r.media.mediaText, scheme) : scheme);
      }
    }
  }
  var done = typeof WeakSet === 'function' ? new WeakSet() : null, doneList = [];
  function seen(s) {
    if (done) { if (done.has(s)) return true; done.add(s); return false; }
    if (doneList.indexOf(s) >= 0) return true; doneList.push(s); return false;
  }
  function baseScheme(rules) {
    var dark = false, light = false;
    (function scan(rs) {
      for (var i = 0; i < rs.length; i++) {
        var r = rs[i];
        if (r.media) {
          var s = schemeOfMedia(r.media.mediaText, '');
          if (s === 'dark') dark = true;
          if (s === 'light') light = true;
        }
      }
    })(rules);
    if (dark && !light) return 'light';
    if (light && !dark) return 'dark';
    return designScheme;
  }
  function processSheets() {
    for (var i = 0; i < doc.styleSheets.length; i++) {
      var s = doc.styleSheets[i], rules;
      if (s.ownerNode && s.ownerNode.id === 'hb-style') continue;
      try { rules = s.cssRules; } catch (e) { continue; }   /* other-origin CSS (CDN): skip */
      if (!rules || seen(s)) continue;
      walk(rules, baseScheme(rules));
    }
  }

  /* ---------- read the HA theme and publish it as variables ---------- */
  var CORE = ['primary-color', 'dark-primary-color', 'light-primary-color', 'accent-color', 'text-primary-color',
    'primary-text-color', 'secondary-text-color', 'disabled-text-color', 'text-light-primary-color',
    'primary-background-color', 'secondary-background-color', 'card-background-color', 'ha-card-background',
    'divider-color', 'error-color', 'warning-color', 'success-color', 'info-color', 'state-icon-color',
    'paper-item-icon-color', 'sidebar-background-color', 'sidebar-text-color', 'app-header-background-color',
    'app-header-text-color', 'ha-card-border-radius', 'ha-card-box-shadow', 'ha-card-border-color',
    'ha-card-border-width', 'primary-font-family', 'paper-font-body1_-_font-family', 'lovelace-background',
    'input-fill-color', 'mdc-theme-primary', 'switch-checked-color', 'table-row-background-color',
    'table-row-alternative-background-color', 'code-editor-background-color', 'markdown-code-background-color'];
  var BLUR_VARS = ['ha-card-backdrop-filter', 'card-backdrop-filter', 'ha-card-backdrop', 'backdrop-filter',
    'glass-blur', 'ha-blur', 'blur', 'card-blur', 'ha-card-blur'];
  var MOD_VARS = ['card-mod-card', 'card-mod-card-yaml', 'card-mod-root', 'card-mod-view', 'card-mod-row'];
  var lastKey = '', copied = {}, wallOverride = null;   /* null = no add-on option set */
  var globalWall = null;                               /* null = no shared wallpaper from Photo Hub */

  function themeSource() {
    var d = HA.document;
    return d.querySelector('home-assistant') || d.documentElement;
  }
  function readTheme() {
    var cs = HA.getComputedStyle(themeSource());
    var g = function (n) { return (cs.getPropertyValue('--' + n) || '').trim(); };
    var th = { vars: {} };
    var names = CORE.slice(), i, st = HA.document.documentElement.style;
    for (i = 0; i < st.length; i++) if (st[i].indexOf('--') === 0) names.push(st[i].slice(2));
    for (i = 0; i < cs.length; i++) if (cs[i].indexOf('--') === 0 && names.length < 900) names.push(cs[i].slice(2));
    names.forEach(function (n) {
      var v = g(n);
      if (v && v.length < 400) th.vars['--' + n] = v;
    });
    var blur = '';
    for (i = 0; i < BLUR_VARS.length && !blur; i++) blur = g(BLUR_VARS[i]);
    for (i = 0; i < MOD_VARS.length && !blur; i++) {
      var m = /backdrop-filter\s*:\s*([^;}!\n]+)/i.exec(g(MOD_VARS[i]));
      if (m) blur = m[1].trim();
    }
    if (/^[\d.]+(px|rem|em)$/.test(blur)) blur = 'blur(' + blur + ')';
    if (/var\(/.test(blur)) blur = '';
    th.blur = blur;
    th.bg = toRGB(g('primary-background-color')) || [17, 17, 17, 1];
    th.bg2 = toRGB(g('secondary-background-color')) || th.bg;
    th.text = toRGB(g('primary-text-color')) || (lum(th.bg) < 0.5 ? [225, 225, 225, 1] : [33, 33, 33, 1]);
    th.text2 = toRGB(g('secondary-text-color')) || th.text;
    th.cardRaw = g('ha-card-background') || g('card-background-color');
    th.card = toRGB(th.cardRaw) || th.bg2;
    th.line = g('divider-color') || 'rgba(' + rgbStr(th.text) + ',.12)';
    th.primary = toRGB(g('primary-color')) || [3, 169, 244, 1];
    th.accent = toRGB(g('accent-color')) || th.primary;
    th.on = toRGB(g('text-primary-color')) || [255, 255, 255, 1];
    th.error = toRGB(g('error-color')) || [219, 68, 55, 1];
    th.warning = toRGB(g('warning-color')) || [255, 166, 0, 1];
    th.success = toRGB(g('success-color')) || [67, 160, 71, 1];
    th.info = toRGB(g('info-color')) || [3, 155, 229, 1];
    th.wall = g('lovelace-background');
    if (th.wall && !/url\(|gradient\(/.test(th.wall) && !toRGB(th.wall)) th.wall = '';
    if (wallOverride !== null) th.wall = wallOverride;
    else if (globalWall !== null) th.wall = globalWall;
    th.radius = g('ha-card-border-radius');
    th.shadow = g('ha-card-box-shadow');
    th.cardBorder = g('ha-card-border-color');
    th.cardBorderW = g('ha-card-border-width');
    th.dark = th.wall ? lum(th.text) > 0.5 : lum(th.bg) < 0.5;
    return th;
  }

  function set(n, v) {
    if (v == null || v === '') root.style.removeProperty(n);
    else root.style.setProperty(n, v);
  }
  function css(c) {
    return c[3] < 1 ? 'rgba(' + rgbStr(c) + ',' + (Math.round(c[3] * 1000) / 1000) + ')' : 'rgb(' + rgbStr(c) + ')';
  }

  /* ---------- wallpaper readability ---------- */
  var dimCache = {};           /* wallpaper url -> {dark: alpha, light: alpha} */
  function lin(v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }
  function relLum(c) { return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2]); }
  function contrast(a, b) { return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05); }
  function wallUrl(w) { var m = /url\(\s*["']?([^"')]+)["']?\s*\)/.exec(w || ''); return m ? m[1] : ''; }
  /* smallest overlay alpha so text over the worst part of the picture still reads */
  function needed(stats, th) {
    /* browsers mix a see-through layer in screen (sRGB) values, so blend those, then measure */
    var out = 0.12, bg = th.bg;
    [[th.text, 4.5], [th.text2, 3.2]].forEach(function (t) {
      var tl = relLum(t[0]), worst = tl > 0.5 ? stats.hi : stats.lo;
      for (var a = 0.12; a <= 0.85; a += 0.02) {
        var mix = [0, 1, 2].map(function (i) { return a * bg[i] + (1 - a) * worst[i]; });
        if (contrast(tl, relLum(mix)) >= t[1]) { out = Math.max(out, a); return; }
      }
      out = Math.max(out, 0.85);
    });
    return Math.round(out * 100) / 100;
  }
  function measure(url, th) {
    if (dimCache[url] || !window.Image) return;
    dimCache[url] = { pending: true };
    var img = new Image();
    if (/^https?:/.test(url) && url.indexOf(location.origin) !== 0) img.crossOrigin = 'anonymous';
    img.onload = function () {
      try {
        var cv = doc.createElement('canvas'), n = 48;
        cv.width = cv.height = n;
        var cx = cv.getContext('2d');
        cx.drawImage(img, 0, 0, n, n);
        var px = cx.getImageData(0, 0, n, n).data, ls = [];
        for (var i = 0; i < px.length; i += 4) {
          var c = [px[i], px[i + 1], px[i + 2]];
          ls.push({ l: relLum(c), c: c });
        }
        ls.sort(function (a, b) { return a.l - b.l; });
        /* 5% darkest / brightest areas: what text over the busiest part of the picture sits on */
        dimCache[url] = { lo: ls[Math.floor(ls.length * 0.05)].c, hi: ls[Math.floor(ls.length * 0.95)].c };
      } catch (e) { dimCache[url] = { failed: true }; }  /* other site without CORS: use a safe default */
      lastKey = ''; apply();
    };
    img.onerror = function () { dimCache[url] = { failed: true }; };
    img.src = url;
  }
  function dimFor(th) {
    var url = wallUrl(th.wall);
    if (!url) return 0;
    var st = dimCache[url];
    if (!st) { measure(url, th); return 0.35; }
    if (st.pending || st.failed) return 0.35;
    return needed(st, th);
  }

  function apply() {
    var th;
    try { th = readTheme(); } catch (e) { return; }
    var key = JSON.stringify(th);
    if (key === lastKey) return;
    lastKey = key;

    /* every HA variable, so new pages can just use var(--primary-color) */
    Object.keys(copied).forEach(function (n) { if (!th.vars[n]) root.style.removeProperty(n); });
    copied = {};
    Object.keys(th.vars).forEach(function (n) {
      if (pageVars[n]) return;
      root.style.setProperty(n, th.vars[n]);
      copied[n] = 1;
    });

    var cardSame = Math.abs(lum(th.card) - lum(th.bg)) < 0.01 && th.card[3] > 0.95 && !th.wall;
    set('--hb-bg', th.wall ? 'rgba(' + rgbStr(th.bg) + ',.45)' : css(th.bg));
    set('--hb-bg2', css(th.bg2));
    set('--hb-card', cardSame ? 'rgba(' + rgbStr(th.text) + ',.05)' : (th.cardRaw && !toRGB(th.cardRaw) ? th.cardRaw : css(th.card)));
    set('--hb-text', css(th.text));
    set('--hb-text2', css(th.text2));
    set('--hb-line', th.line);
    set('--hb-primary', css(th.primary));
    set('--hb-accent', css(th.accent));
    set('--hb-on', css(th.on));
    ['error', 'warning', 'success', 'info'].forEach(function (k) { set('--hb-' + k, css(th[k])); });
    ['text', 'bg', 'primary', 'accent', 'error', 'warning', 'success', 'info'].forEach(function (k) {
      set('--hb-' + k + '-rgb', rgbStr(th[k]));
    });
    set('--hb-field', 'rgba(' + rgbStr(th.text) + ',' + (th.dark ? '.07' : '.05') + ')');
    set('--hb-inset', 'rgba(' + rgbStr(th.bg) + ',' + (th.wall ? '.35' : '.6') + ')');
    set('--hb-bar', th.card[3] < 0.95 || th.wall ? 'var(--hb-card)' : 'rgba(' + rgbStr(th.bg) + ',.92)');
    set('--hb-blur', th.blur || 'none');
    set('--hb-radius', th.radius);
    set('--hb-shadow', th.shadow);
    set('--hb-card-border', th.cardBorder);
    set('--hb-card-border-width', th.cardBorderW);
    var dim = th.wall ? dimFor(th) : 0, veil = 'rgba(' + rgbStr(th.bg) + ',' + dim + ')';
    set('--hb-dim', String(dim));
    set('--hb-page', th.wall ? (dim ? 'linear-gradient(' + veil + ',' + veil + ') fixed, ' : '') + th.wall : css(th.bg));
    root.style.setProperty('color-scheme', th.dark ? 'dark' : 'light');
    /* a frame whose page and frame element disagree on color-scheme gets an opaque backdrop; keep them equal */
    try { if (window.frameElement) window.frameElement.style.colorScheme = th.dark ? 'dark' : 'light'; } catch (e) { /* cross-origin */ }
    root.classList.toggle('hb-dark', th.dark);
    root.classList.toggle('hb-light', !th.dark);
    root.classList.toggle('hb-wallpaper', !!th.wall);
    root.classList.toggle('hb-glass', !!th.blur);

    var s = doc.getElementById('hb-style');
    if (!s) {
      s = doc.createElement('style');
      s.id = 'hb-style';
      (doc.head || root).appendChild(s);
    }
    var page = nested && th.wall ? 'transparent' : 'var(--hb-page)';
    s.textContent =
      'html.hb-themed{background:' + page + ' !important;min-height:100%}' +
      'html.hb-themed body{background:transparent !important;color:var(--hb-text)}' +
      (th.wall ? 'html.hb-themed iframe{background:transparent !important}' +
        'html.hb-themed.hb-wallpaper body{text-shadow:0 1px 3px rgba(' + rgbStr(th.bg) + ',.55)}' +
        'html.hb-themed.hb-wallpaper input,html.hb-themed.hb-wallpaper textarea,html.hb-themed.hb-wallpaper select{text-shadow:none}' : '') +
      'html.hb-themed ::placeholder{color:var(--hb-text2);opacity:.8}';
    root.classList.add('hb-themed');
  }

  /* ---------- per add-on wallpaper option ---------- */
  function wallCss(v) {
    v = String(v == null ? '' : v).trim();
    if (!v || /^(theme|default|auto)$/i.test(v)) return null;
    if (/^(none|off|no)$/i.test(v)) return '';
    if (/url\(|gradient\(/.test(v)) return v;
    v = v.replace(/^\/?(config|homeassistant)\/www\//, '/local/').replace(/^www\//, '/local/');
    if (!/^(https?:)?\/\//.test(v) && v.charAt(0) !== '/') v = '/local/' + v;
    return 'center / cover no-repeat fixed url("' + v.replace(/"/g, '%22') + '")';
  }
  function loadWallpaperOption() {
    var m = /^\/api\/hassio_ingress\/[^/]+\//.exec(location.pathname);
    var el = themeSource(), hass = el && el.hass;
    if (!m || !hass || !hass.callWS || !(hass.user && hass.user.is_admin)) return;
    var base = m[0], key = 'hb-addon:' + base, hint = window.__hbAddon || '';
    var call = function (ep) {
      return hass.callWS({ type: 'supervisor/api', endpoint: ep, method: 'get' });
    };
    var ingressOf = function (info) { return String((info && (info.ingress_url || info.ingress_entry)) || ''); };
    var useInfo = function (info) {
      var o = (info && info.options) || {};
      wallOverride = 'wallpaper' in o ? wallCss(o.wallpaper) : null;
      lastKey = '';
      apply();
    };
    var cached = '';
    try { cached = sessionStorage.getItem(key) || ''; } catch (e) {}
    var find = function () {
      return call('/addons').then(function (r) {
        var list = (r && r.addons) || r || [], slugs = list.map(function (a) { return a.slug; });
        if (hint) slugs.sort(function (a, b) {
          var ha = a === hint || a.slice(-hint.length - 1) === '_' + hint, hb = b === hint || b.slice(-hint.length - 1) === '_' + hint;
          return (hb ? 1 : 0) - (ha ? 1 : 0);
        });
        var i = 0;
        var next = function () {
          if (i >= slugs.length || i >= 60) return null;
          var slug = slugs[i++];
          return call('/addons/' + slug + '/info').then(function (info) {
            if (ingressOf(info) && base.indexOf(ingressOf(info).replace(/\/?$/, '/')) === 0) {
              try { sessionStorage.setItem(key, slug); } catch (e) {}
              return info;
            }
            return next();
          }, next);
        };
        return next();
      });
    };
    (cached ? call('/addons/' + cached + '/info').then(function (info) {
      return ingressOf(info) && base.indexOf(ingressOf(info).replace(/\/?$/, '/')) === 0 ? info : find();
    }, find) : find()).then(function (info) { if (info) useInfo(info); }, function () {});
  }

  /* ---------- shared add-on wallpaper (picked in Photo Hub) ---------- */
  function loadGlobalWallpaper() {
    if (!window.fetch) return;
    fetch('/local/addon-wallpaper/wallpaper.json?t=' + Date.now(), { cache: 'no-store', credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        var next = d && d.url ? wallCss(d.url) : null;
        if (next !== globalWall) { globalWall = next; lastKey = ''; apply(); }
      }, function () {});
  }

  /* ---------- run now, then follow changes ---------- */
  function run() { try { processSheets(); } catch (e) {} apply(); }
  run();
  var tm = null;
  function later() { clearTimeout(tm); tm = setTimeout(run, 120); }
  try {
    var mo = new HA.MutationObserver(later);
    mo.observe(HA.document.documentElement, { attributes: true, attributeFilter: ['style', 'class'] });
    mo.observe(themeSource(), { attributes: true, attributeFilter: ['style', 'class'] });
    if (HA.document.head) mo.observe(HA.document.head, { childList: true, subtree: true, characterData: true });
    var mq = HA.matchMedia('(prefers-color-scheme: dark)');
    if (mq.addEventListener) mq.addEventListener('change', later); else if (mq.addListener) mq.addListener(later);
  } catch (e) {}
  try {
    new MutationObserver(function (list) {
      for (var i = 0; i < list.length; i++) {
        for (var j = 0; j < list[i].addedNodes.length; j++) {
          var n = list[i].addedNodes[j];
          if (n.id === 'hb-style') continue;
          if (n.tagName === 'STYLE') later();
          if (n.tagName === 'LINK') n.addEventListener('load', later);
        }
      }
    }).observe(doc.head || root, { childList: true });
  } catch (e) {}
  doc.addEventListener('visibilitychange', function () { if (!doc.hidden) { later(); loadGlobalWallpaper(); } });
  window.addEventListener('load', later);
  try { loadWallpaperOption(); } catch (e) {}
  try { loadGlobalWallpaper(); } catch (e) {}
  window.haThemeBridge = { refresh: function () { lastKey = ''; run(); }, reloadWallpaper: loadGlobalWallpaper };
})();
</script>
<!-- /ha-theme -->"""

CSS = """
*{box-sizing:border-box}
body{font-family:-apple-system,system-ui,sans-serif;background:#111827;color:#e5e7eb;margin:0;padding:16px;max-width:680px;font-size:17px;line-height:1.4}
h1{font-size:1.5em;margin:0 0 4px}h3{margin:0 0 8px}
.card{background:#252b3b;border-radius:16px;padding:16px;margin:14px 0}
.muted{color:#9ca3af;font-size:.88em}.ok{color:#4ade80}.warn{color:#fbbf24}.bad{color:#f87171}
.aiout{white-space:pre-wrap;margin-top:10px;line-height:1.5}
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
    days = int(secs // 86400)
    return f"{days} day ago" if days == 1 else f"{days} days ago"


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
    failing = acct.status == "ok" and acct.message.startswith("Update failed")
    if failing:
        cls, label = "warn", "Connected, but the last update failed"
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
        out.append(f"<form method='post' action='retry'>{hidden}<button class='grey'>{'Retry anyway (can extend the block)' if acct.throttle_count else 'Retry login'}</button></form>")
    elif failing:
        out.append(f"<form method='post' action='retry'>{hidden}<button>Reconnect</button></form>")
    if acct.status == "error" or failing:
        out.append(
            f"<form method='post' action='password'>{hidden}"
            "<div class='muted' style='margin-top:12px'>Changed your Apple password? Update it here</div>"
            "<input type='password' name='password' placeholder='New password' autocomplete='off'>"
            "<button class='grey'>Save password and reconnect</button></form>"
        )
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

    trouble = acct.status != "ok" or failing
    ans = getattr(acct, "ai_answer", "")
    out.append(
        "<div class='card'><h3>\u2728 Ask AI</h3>"
        f"<form method='post' action='ai'>{hidden}"
        + ("<div class='muted'>Explains what's wrong with this account and what to do.</div><input type='hidden' name='q' value=''>"
           if trouble else "<input type='text' name='q' placeholder='Which phone needs charging? Who hasn\u2019t updated lately?' autocomplete='off'>")
        + f"<button class='grey'>{'Explain the problem' if trouble else 'Ask'}</button></form>"
        + (f"<div class='aiout'>{esc(ans)}</div>" if ans else "") + "</div>"
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
        "<input type='text' name='label' placeholder='Tab name (optional, like Alex or Sam)' autocomplete='off'>"
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
        f"<title>iCloud Lite</title><style>{CSS}</style></head><body>{HA_THEME}"
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
            log.info("Account added: %s", acct.tag)
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
                log.info("%s: device added: %s", acct.tag, acct.devices.get(dev_id, dev_id[:8]))
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
                log.info("%s: device removed: %s", acct.tag, acct.devices.get(dev_id, dev_id[:8]))
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
            log.info("%s: manual reconnect requested", acct.tag)
            acct.status, acct.api, acct.next_login = "login", None, 0
        return go(acct.id if acct else None)

    @routes.post("/password")
    async def password(request):
        data, acct = await get_acct(request)
        if acct and data.get("password"):
            acct.password = data["password"]
            log.info("%s: password updated, reconnecting", acct.tag)
            acct.status, acct.api, acct.next_login = "login", None, 0
            app_state.save()
        return go(acct.id if acct else None)

    @routes.post("/ai")
    async def ai(request):
        data, acct = await get_acct(request)
        if not acct:
            return go()
        import ha_ai
        devs = []
        for d in acct.selected or list(acct.devices)[:12]:
            info = acct.info.get(d, {})
            loc = info.get("location") or {}
            devs.append("%s: %s, location %s" % (acct.names.get(d) or acct.devices.get(d, d), describe(info) if info else "not reported",
                        "%.4f,%.4f" % (loc["latitude"], loc["longitude"]) if loc.get("latitude") else "none"))
        q = str(data.get("q") or "").strip()[:500]
        prompt = ("A Home Assistant add-on tracks Apple devices through iCloud (pyicloud). Account status: %s. Last message: %s. "
                  "Login retries blocked: %s. Update interval %s min, fast near zones %s s.\nDevices:\n%s\n\n"
                  % (acct.status, acct.message or "none", acct.throttle_count or 0, acct.interval, acct.fast_interval, "\n".join(devs) or "none"))
        prompt += ("Answer this briefly and plainly: " + q) if q else (
            "Explain in plain words what is wrong and exactly what to do in this add-on (2FA code, password, waiting out an "
            "Apple rate limit, etc.). Short. If nothing is wrong, say so.")
        try:
            ent = json.loads((DATA / "options.json").read_text()).get("ai_task_entity") or ""
        except Exception:  # noqa: BLE001
            ent = ""
        try:
            acct.ai_answer = await asyncio.get_running_loop().run_in_executor(None, ha_ai.ask, prompt, ent, "iCloud Lite")
        except Exception as e:  # noqa: BLE001
            acct.ai_answer = str(e)
        return go(acct.id)

    @routes.post("/remove")
    async def remove(request):
        _, acct = await get_acct(request)
        if acct:
            log.info("Account removed: %s", acct.tag)
            app_state.remove_account(acct)
        return go()

    web_app = web.Application(middlewares=[ingress_only])
    web_app.add_routes(routes)
    return web_app


def setup_logging():
    """Apply the log_level / log_pyicloud options from the add-on Configuration tab."""
    opts = {}
    try:
        opts = json.loads((DATA / "options.json").read_text())
    except Exception:  # noqa: BLE001
        pass
    level = getattr(logging, str(opts.get("log_level") or "info").upper(), logging.INFO)
    logging.basicConfig(
        level=level, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S", force=True
    )
    for noisy in ("urllib3", "asyncio", "aiohttp", "charset_normalizer", "requests"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # pyicloud's own debug output can contain sensitive request details, so it has its own switch
    logging.getLogger("pyicloud").setLevel(logging.DEBUG if opts.get("log_pyicloud") else logging.WARNING)
    log.info(
        "Log level: %s | pyicloud debug: %s",
        logging.getLevelName(level),
        "ON (sensitive!)" if opts.get("log_pyicloud") else "off",
    )
    return level


async def main():
    level = setup_logging()
    state = App()
    web_app = build_web(state)
    runner = web.AppRunner(web_app, access_log=logging.getLogger('aiohttp.access') if level <= logging.DEBUG else None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8099).start()
    log.info("Web UI up on :8099 with %d saved account(s)", len(state.accounts))
    await asyncio.gather(state.mqtt_connector(), state.worker(), state.zone_refresher())


if __name__ == "__main__":
    asyncio.run(main())
