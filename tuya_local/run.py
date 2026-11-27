"""Local Devices: finds your Tuya devices on the network, talks to them directly (no cloud needed to control them) and
publishes them to Home Assistant through MQTT discovery. The Tuya account is only used once, to get each device's
local key."""
import asyncio
import ipaddress
import json
import os
import queue
import re
import shutil
import socket
import subprocess
import threading
import time
import urllib.request

import paho.mqtt.client as mqtt
import requests
import tinytuya
from tinytuya import scanner as tt_scanner
from aiohttp import web

import tuya_cloud as C
import tuya_model as M

DATA_DIR = os.environ.get("TUYA_DATA_DIR", "/data")
HA_CONFIG = os.environ.get("TUYA_HA_CONFIG", "/homeassistant")
PORT = int(os.environ.get("TUYA_PORT", "8765"))
TEST = bool(os.environ.get("TUYA_TEST"))
STORE_FILE = os.path.join(DATA_DIR, "tuya.json")
BASE = "tuya_local"
VERSIONS = ["3.3", "3.4", "3.5", "3.1", "3.2"]
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
ALLOWED = [ipaddress.ip_network(n) for n in ("127.0.0.0/8", "::1/128", "172.30.32.0/23")]  # this machine and the Supervisor

try:
    OPT = json.load(open(os.path.join(DATA_DIR, "options.json")))
except (OSError, ValueError):
    OPT = {}


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


# ---------- saved data ----------
class Store:
    def __init__(self):
        self.lock = threading.RLock()
        self.d = {"auth": None, "devices": {}}
        try:
            with open(STORE_FILE) as f:
                self.d.update(json.load(f))
        except (OSError, ValueError):
            pass

    def save(self):
        with self.lock:
            os.makedirs(DATA_DIR, exist_ok=True)
            tmp = STORE_FILE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.d, f, indent=1)
            os.replace(tmp, STORE_FILE)
            try:
                os.chmod(STORE_FILE, 0o600)  # it holds the devices' local keys
            except OSError:
                pass


store = Store()
sent = []  # test mode: every MQTT message that would have been sent


# ---------- plain-English explanation of tinytuya errors ----------
def explain(err):
    """(short text, hint) for an error dict from tinytuya or an exception text."""
    text = str(err.get("Error") if isinstance(err, dict) else err or "")
    code = str(err.get("Err") if isinstance(err, dict) else "")
    low = text.lower()
    if code in ("914", "904", "900") or "key or version" in low or "unexpected payload" in low or "decrypt" in low or "json" in low:
        return ("Connected, but the reply could not be read",
                "Wrong local key or protocol version. If you re-paired the device in the Tuya app its key changed: "
                "open the Account tab and tap Get my devices to fetch the new key.")
    if "reset" in low or "104" in low or "refused" in low or "unable to connect" in low or code == "901":
        return ("The device refuses the connection",
                "A Tuya device only allows one local connection at a time. Close the Tuya Smart / Smart Life app on your "
                "phones, and switch off any other Tuya add-on or integration (like LocalTuya) that uses this device. "
                "If that is not it, the IP address may have changed: run Find devices.")
    if code in ("905", "917") or "unreachable" in low or "timed out" in low or "timeout" in low or "no route" in low:
        return ("The device does not answer",
                "It may be unplugged, on weak Wi-Fi, or its IP address changed. Run Find devices, and check that this "
                "add-on and the device are on the same network.")
    return (text or "Could not connect", "Try Check connection on this device for a step by step test.")


def tcp_check(ip, port=6668, timeout=3):
    """('open'|'refused'|'reset'|'timeout'|'unreachable', detail)."""
    try:
        with socket.create_connection((ip, port), timeout):
            return "open", "The device accepted a connection on port %d." % port
    except ConnectionResetError as e:
        return "reset", str(e)
    except ConnectionRefusedError as e:
        return "refused", str(e)
    except socket.timeout:
        return "timeout", "No answer within %d seconds." % timeout
    except OSError as e:
        return ("reset" if getattr(e, "errno", 0) == 104 else "unreachable"), str(e)


# ---------- the hub ----------
class Hub:
    def __init__(self):
        self.workers = {}
        self.dps = {}          # device id -> latest data points
        self.info = {}         # device id -> {state, error, hint, since, version}
        self.last_pub = {}     # (device id, entity id) -> last state sent
        self.seen = {}         # device id -> {ip, version, ts} from the last scan
        self.client = None
        self.scan_lock = threading.Lock()
        self.scan = {"running": False, "ts": 0, "found": [], "error": ""}
        self.pending_qr = None

    # ---- devices
    def dev(self, did):
        return store.d["devices"].get(did)

    def update(self, did, **kw):
        with store.lock:
            d = self.dev(did)
            if d is not None:
                d.update(kw)
                store.save()

    def start_worker(self, did):
        w = self.workers.get(did)
        if w is None or not w.is_alive():
            w = Worker(self, did)
            self.workers[did] = w
            w.start()
        else:
            w.wake()

    def start_all(self):
        for did in list(store.d["devices"]):
            self.start_worker(did)

    # ---- MQTT
    def publish(self, topic, payload, retain=True):
        if TEST:
            sent.append((topic, payload))
        if self.client is not None:
            try:
                self.client.publish(topic, payload, qos=1, retain=retain)
            except Exception as e:
                log("MQTT publish failed:", e)

    def publish_device(self, dev, old_entities=None):
        keep = set()
        for e in dev.get("entities", []):
            topic, cfg = M.discovery(dev, e, BASE)
            if e.get("enabled", True) and dev.get("enabled", True):
                self.publish(topic, json.dumps(cfg))
                keep.add(topic)
        for e in (old_entities or []) + dev.get("entities", []):
            topic, _ = M.discovery(dev, e, BASE)
            if topic not in keep:
                self.publish(topic, "")  # removes it from Home Assistant
        for e in dev.get("entities", []):
            self.last_pub.pop((dev["id"], e["id"]), None)
        self.publish_states(dev["id"])

    def remove_device(self, dev):
        for e in dev.get("entities", []):
            self.publish(M.discovery(dev, e, BASE)[0], "")
        self.publish(f"{BASE}/{dev['id']}/available", "")

    def publish_states(self, did):
        dev, dps = self.dev(did), self.dps.get(did) or {}
        if not dev:
            return
        for e in dev.get("entities", []):
            if not e.get("enabled", True):
                continue
            s = M.entity_state(e, dps)
            key = (did, e["id"])
            if s is not None and self.last_pub.get(key) != s:
                self.last_pub[key] = s
                self.publish(f"{BASE}/{did}/{e['id']}/state", s)

    def set_available(self, did, on):
        self.publish(f"{BASE}/{did}/available", "online" if on else "offline")

    def republish_all(self):
        for dev in list(store.d["devices"].values()):
            self.publish_device(dev)
            self.set_available(dev["id"], self.info.get(dev["id"], {}).get("state") == "online")

    def start_mqtt(self):
        if TEST:
            return
        try:
            host = (OPT.get("mqtt_host") or "").strip()
            if host:
                c = {"host": host, "port": OPT.get("mqtt_port") or 1883, "username": (OPT.get("mqtt_username") or "").strip() or None,
                     "password": OPT.get("mqtt_password") or None, "ssl": False}
            else:
                req = urllib.request.Request("http://supervisor/services/mqtt", headers={"Authorization": f"Bearer {TOKEN}"})
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
            cl.on_connect = self.on_connect
            cl.on_message = self.on_message
            cl.connect_async(c["host"], int(c.get("port", 1883)), 60)
            cl.loop_start()
            self.client = cl
        except Exception as e:
            log("MQTT not available:", e, "- entities cannot be created until the Mosquitto broker is running")

    def on_connect(self, cl, *a, **k):
        cl.subscribe([(f"{BASE}/+/+/set", 1), ("homeassistant/status", 1)])
        self.publish(f"{BASE}/status", "online")
        self.republish_all()
        log("MQTT connected")

    def on_message(self, cl, ud, msg):
        payload = msg.payload.decode("utf-8", "replace")
        if msg.topic == "homeassistant/status":
            if payload == "online":
                self.republish_all()
            return
        parts = msg.topic.split("/")
        if len(parts) == 4 and parts[0] == BASE and parts[3] in ("set", "fan"):
            ok, why = self.command(parts[1], parts[2], ("fan:" + payload) if parts[3] == "fan" else payload)
            if not ok:
                log("Command not sent:", why)

    # ---- commands
    def command(self, did, eid, payload):
        dev = self.dev(did)
        if not dev:
            return False, "unknown device"
        ent = next((e for e in dev.get("entities", []) if e["id"] == eid), None)
        if not ent:
            return False, "unknown entity"
        cmd = M.entity_command(ent, payload)
        if not cmd:
            return False, "nothing to send for that value"
        w = self.workers.get(did)
        if not w or self.info.get(did, {}).get("state") != "online":
            return False, "the device is not connected"
        w.q.put(cmd)
        return True, ""

    # ---- data from devices
    def apply_dps(self, did, dps):
        cur = self.dps.setdefault(did, {})
        cur.update({str(k): v for k, v in dps.items()})
        dev = self.dev(did)
        if dev and dev.get("needs_inference"):
            taken = {dp for e in dev.get("entities", []) for dp in M.dps_used(e)}
            new = M.entities_from_values(cur, taken)
            with store.lock:
                old = list(dev.get("entities", []))
                dev["entities"] = old + new
                dev["needs_inference"] = False
                store.save()
            log(f"{dev.get('name') or did}: found {len(new)} more data points on the device")
            self.publish_device(dev, old)
        else:
            self.publish_states(did)

    def set_info(self, did, state, error="", hint="", version=None):
        old = self.info.get(did, {})
        self.info[did] = {"state": state, "error": error, "hint": hint, "version": version or old.get("version"),
                          "since": old["since"] if old.get("state") == state and old.get("error") == error else time.time()}
        if old.get("state") != state:
            self.set_available(did, state == "online")

    # ---- scan
    def run_scan(self, seconds=12):
        if not self.scan_lock.acquire(blocking=False):
            return
        self.scan.update(running=True, error="")
        try:
            os.makedirs(DATA_DIR, exist_ok=True)
            os.chdir(DATA_DIR)  # tinytuya looks for devices.json in the current folder
            res = tt_scanner.devices(verbose=False, scantime=seconds, color=False, poll=False, assume_yes=True,
                                           tuyadevices=[{"id": "none", "name": "", "key": ""}], byID=False)
            found = []
            for ip, v in (res or {}).items():
                did = v.get("gwId") or v.get("id") or ""
                if not did:
                    continue
                ver = str(v.get("version") or "")
                self.seen[did] = {"ip": v.get("ip") or ip, "version": ver, "ts": time.time()}
                dev = self.dev(did)
                changed = False
                if dev and dev.get("ip") != self.seen[did]["ip"]:
                    self.update(did, ip=self.seen[did]["ip"])
                    changed = True
                    log(f"{dev.get('name') or did} is now at {self.seen[did]['ip']}")
                if dev and changed:
                    self.start_worker(did)
                found.append({"id": did, "ip": self.seen[did]["ip"], "version": ver, "product_key": v.get("productKey", ""),
                              "known": bool(dev), "name": (dev or {}).get("name", "")})
            found.sort(key=lambda x: (x["known"], x["ip"]))
            self.scan.update(found=found, ts=time.time())
            log(f"Scan finished: {len(found)} device(s) answered")
        except Exception as e:
            self.scan["error"] = str(e)
            log("Scan failed:", e)
        finally:
            self.scan["running"] = False
            self.scan_lock.release()

    def scan_in_background(self):
        threading.Thread(target=self.run_scan, daemon=True).start()

    def housekeeping(self):
        """Every minute: if a device is offline and nothing scanned lately, scan to catch changed IP addresses."""
        time.sleep(8)
        self.run_scan()
        while True:
            time.sleep(60)
            offline = [d for d, i in self.info.items() if i.get("state") not in ("online", "disabled") and self.dev(d)]
            if offline and time.time() - self.scan["ts"] > 180:
                self.run_scan()


hub = Hub()


# ---------- one connection per device ----------
class Worker(threading.Thread):
    def __init__(self, hub, did):
        super().__init__(daemon=True, name=f"tuya-{did[:6]}")
        self.hub, self.did = hub, did
        self.q = queue.Queue()
        self.reconnect = threading.Event()   # the session should end and start again (IP, key or version changed)
        self.suspended = False
        self.idle = threading.Event()        # set while no connection is open

    def wake(self):
        self.reconnect.set()

    def versions(self, dev):
        first = []
        for v in (self.hub.seen.get(self.did, {}).get("version"), dev.get("version")):
            if v in VERSIONS and v not in first:
                first.append(v)
        return first + [v for v in VERSIONS if v not in first]

    def open(self, dev, ip):
        """Try the protocol versions in turn; returns (device, first status, version)."""
        last = None
        for v in self.versions(dev):
            self.hub.set_info(self.did, "connecting", hint=f"Trying protocol {v}...")
            d = tinytuya.Device(dev["id"], ip, dev["key"], version=float(v), persist=True, connection_timeout=4,
                                connection_retry_limit=1, connection_retry_delay=1)
            d.set_socketPersistent(True)
            st = d.status()
            if isinstance(st, dict) and st.get("dps"):
                return d, st, v
            last = st
            try:
                d.close()
            except Exception:
                pass
            if isinstance(st, dict) and str(st.get("Err")) in ("905",):
                break  # no point trying other versions when the device does not answer at all
        raise ConnectionError(last if isinstance(last, dict) else {"Error": str(last)})

    def session(self, dev):
        ip = dev.get("ip") or self.hub.seen.get(self.did, {}).get("ip")
        if not ip:
            self.hub.set_info(self.did, "waiting", "No IP address yet", "Run Find devices, or type the IP address in the device settings.")
            raise LookupError("no ip")
        if not dev.get("key"):
            self.hub.set_info(self.did, "waiting", "No local key yet", "Open the Account tab and sign in, then tap Get my devices (or type the key in the device settings).")
            raise LookupError("no key")
        self.hub.set_info(self.did, "connecting")
        state, detail = tcp_check(ip)
        if state != "open":
            short, hint = explain({"Error": state + " " + detail})
            if state in ("timeout", "unreachable"):
                short, hint = explain({"Err": "905"})
            raise ConnectionError({"Error": short, "hint": hint})
        d, st, v = self.open(dev, ip)
        if dev.get("version") != v:
            self.hub.update(self.did, version=v)
            log(f"{dev.get('name') or self.did}: using protocol {v}")
        self.hub.set_info(self.did, "online", version=v)
        log(f"{dev.get('name') or self.did}: connected ({ip}, protocol {v})")
        self.hub.apply_dps(self.did, st["dps"])
        last_hb = last_poll = time.time()
        try:
            while not self.reconnect.is_set() and not self.suspended:
                try:
                    while True:
                        cmd = self.q.get_nowait()
                        if len(cmd) == 1:
                            k, val = next(iter(cmd.items()))
                            d.set_value(k, val, nowait=True)
                        else:
                            d.set_multiple_values(cmd, nowait=True)
                except queue.Empty:
                    pass
                data = d.receive()
                if isinstance(data, dict):
                    if data.get("Error"):
                        raise ConnectionError(data)
                    dps = data.get("dps") or (data.get("data") or {}).get("dps")
                    if dps:
                        self.hub.apply_dps(self.did, dps)
                now = time.time()
                if now - last_hb > 9:
                    d.heartbeat(nowait=True)
                    last_hb = now
                if now - last_poll > 90:
                    st = d.status()
                    if isinstance(st, dict) and st.get("Error"):
                        raise ConnectionError(st)
                    if isinstance(st, dict) and st.get("dps"):
                        self.hub.apply_dps(self.did, st["dps"])
                    last_poll = now
        finally:
            try:
                d.close()
            except Exception:
                pass

    def run(self):
        delay = 4
        while True:
            dev = self.hub.dev(self.did)
            if dev is None:
                return  # deleted
            self.reconnect.clear()
            if not dev.get("enabled", True):
                self.hub.set_info(self.did, "disabled")
                self.reconnect.wait(30)
                continue
            if self.suspended:
                self.idle.set()
                time.sleep(1)
                continue
            self.idle.clear()
            try:
                self.session(dev)
                delay = 4
                if not self.reconnect.is_set() and not self.suspended:
                    self.hub.set_info(self.did, "offline", "Connection lost", "The add-on will keep trying.")
            except LookupError:
                pass
            except ConnectionError as e:
                err = e.args[0] if e.args and isinstance(e.args[0], dict) else {"Error": str(e)}
                short, hint = (err["Error"], err["hint"]) if err.get("hint") else explain(err)
                self.hub.set_info(self.did, "error", short, hint)
                log(f"{dev.get('name') or self.did}: {short}")
            except Exception as e:
                short, hint = explain(str(e))
                self.hub.set_info(self.did, "error", short, hint)
                log(f"{dev.get('name') or self.did}: {e!r}")
            self.idle.set()
            self.reconnect.wait(delay)
            delay = min(delay * 2, 60)


def diagnose(did):
    """Step by step test of one device. Pauses its normal connection first (a device accepts only one)."""
    dev = hub.dev(did)
    if not dev:
        return {"ok": False, "steps": [], "verdict": "Unknown device."}
    w = hub.workers.get(did)
    if w:
        w.suspended = True
        w.reconnect.set()
        w.idle.wait(8)
    steps, verdict, fixed = [], "", None
    try:
        ip = dev.get("ip") or hub.seen.get(did, {}).get("ip") or ""
        seen = hub.seen.get(did)
        steps.append({"title": "Is it on the network?", "ok": bool(seen),
                      "detail": (f"Found at {seen['ip']} (protocol {seen['version'] or 'unknown'}) by the last scan." if seen
                                 else "The last scan did not hear this device. It may be off, or on another network.")})
        if seen and seen["ip"] != ip:
            ip = seen["ip"]
            hub.update(did, ip=ip)
            steps.append({"title": "IP address", "ok": True, "detail": f"It moved. Saved the new address {ip}."})
        if not ip:
            verdict = "No IP address. Run Find devices, or type the IP address into the device settings."
            return {"ok": False, "steps": steps, "verdict": verdict}
        state, detail = tcp_check(ip)
        steps.append({"title": f"Port 6668 at {ip}", "ok": state == "open", "detail": detail})
        if state != "open":
            verdict = explain({"Error": state + " " + detail} if state in ("reset", "refused") else {"Err": "905"})[1]
            return {"ok": False, "steps": steps, "verdict": verdict}
        if not dev.get("key"):
            return {"ok": False, "steps": steps, "verdict": "There is no local key for this device yet. Use the Account tab to fetch it."}
        order = ([seen["version"]] if seen and seen.get("version") in VERSIONS else []) + VERSIONS
        tried = []
        for v in order:
            if v in tried:
                continue
            tried.append(v)
            d = tinytuya.Device(dev["id"], ip, dev["key"], version=float(v), persist=False, connection_timeout=4,
                                connection_retry_limit=1, connection_retry_delay=1)
            st = d.status()
            ok = isinstance(st, dict) and bool(st.get("dps"))
            steps.append({"title": f"Talk using protocol {v}", "ok": ok,
                          "detail": "Got an answer: %d data points." % len(st["dps"]) if ok else explain(st)[0]})
            if ok:
                fixed = v
                hub.update(did, version=v)
                hub.apply_dps(did, st["dps"])
                verdict = f"Works with protocol {v}. Saved. The device will reconnect by itself."
                break
        if not fixed:
            verdict = ("The device answers but not with this key. " + explain({"Err": "914"})[1])
        return {"ok": bool(fixed), "steps": steps, "verdict": verdict, "version": fixed}
    finally:
        if w:
            w.suspended = False
            w.reconnect.set()


# ---------- web ----------
def device_view(d):
    did = d["id"]
    info = hub.info.get(did, {"state": "starting"})
    key = d.get("key") or ""
    ents = []
    for e in d.get("entities", []):
        item = {"id": e["id"], "name": e["name"], "platform": e["platform"], "enabled": e.get("enabled", True),
                "value": hub.last_pub.get((did, e["id"]))}
        if e["platform"] == "select" or (e["platform"] == "sensor" and e.get("options")):
            item["options"], item["labels"] = e.get("options", []), e.get("labels") or {}
        if e["platform"] == "vacuum" and e.get("fan"):
            item["options"], item["labels"], item["fan"] = e["fan"].get("options", []), e["fan"].get("labels") or {}, True
        ents.append(item)
    return {"id": did, "name": d.get("name") or did, "ip": d.get("ip", ""), "version": d.get("version", "auto"),
            "enabled": d.get("enabled", True), "category": d.get("category", ""), "product_name": d.get("product_name", ""),
            "has_key": bool(key), "key_tail": key[-4:] if key else "", "state": info.get("state"), "error": info.get("error", ""),
            "hint": info.get("hint", ""), "since": info.get("since"), "protocol": info.get("version"), "entities": ents,
            "needs_inference": bool(d.get("needs_inference"))}


@web.middleware
async def only_local(request, handler):
    try:
        ip = ipaddress.ip_address(request.remote or "127.0.0.1")
    except ValueError:
        raise web.HTTPForbidden()
    if not any(ip in n for n in ALLOWED):
        raise web.HTTPForbidden(text="This page is only available through Home Assistant.")
    return await handler(request)


async def index(r):
    return web.Response(text=open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "index.html"), encoding="utf-8").read(),
                        content_type="text/html", headers={"Cache-Control": "no-store"})



# ---------- Cloud Intelligence key capture (a proxy you start on purpose) ----------
CI_FILE = os.environ.get("CI_KEYS_FILE", "/tmp/ci_keys.json")
CI_PORT = 8080
CI_MINUTES = 30
ci = {"proc": None, "until": 0.0}


def ci_running():
    p = ci["proc"]
    if p and p.poll() is None:
        if time.time() > ci["until"]:
            ci_stop()
            return False
        return True
    return False


def ci_stop():
    p = ci["proc"]
    ci["proc"] = None
    if p and p.poll() is None:
        p.terminate()
        try:
            p.wait(5)
        except subprocess.TimeoutExpired:
            p.kill()


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("192.0.2.1", 9))  # no packet is sent; this only picks the interface
        return s.getsockname()[0]
    except OSError:
        return ""
    finally:
        s.close()


def ci_keys():
    try:
        with open(CI_FILE) as f:
            return json.load(f)
    except (OSError, ValueError):
        return []


async def get_ci(r):
    run = ci_running()
    return web.json_response({"running": run, "ip": lan_ip(), "port": CI_PORT, "minutes_left": max(0, int((ci["until"] - time.time()) / 60)) if run else 0,
                              "available": bool(shutil.which("mitmdump")), "keys": ci_keys()})


async def post_ci_start(r):
    exe = shutil.which("mitmdump")
    if not exe:
        return web.json_response({"ok": False, "error": "The capture tool (mitmproxy) is not installed in this add-on build."}, status=500)
    if not ci_running():
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ci_capture.py")
        env = dict(os.environ, CI_KEYS_FILE=CI_FILE)
        ci["proc"] = subprocess.Popen([exe, "-q", "--listen-port", str(CI_PORT), "--set", "confdir=/tmp/mitm", "-s", script], env=env,
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ci["until"] = time.time() + CI_MINUTES * 60
    time.sleep(1)
    if ci["proc"].poll() is not None:
        ci["proc"] = None
        return web.json_response({"ok": False, "error": "The capture proxy would not start. Is port %d already in use?" % CI_PORT}, status=500)
    return web.json_response({"ok": True})


async def post_ci_stop(r):
    ci_stop()
    try:
        os.remove(CI_FILE)  # keys do not stay on disk once you are done
    except OSError:
        pass
    return web.json_response({"ok": True})


async def get_state(r):
    a = store.d.get("auth")
    devs = sorted((device_view(d) for d in store.d["devices"].values()), key=lambda x: x["name"].lower())
    return web.json_response({"devices": devs, "signed_in": bool(a), "user_code": (a or {}).get("user_code", ""),
                              "scan": hub.scan, "mqtt": TEST or (hub.client is not None and hub.client.is_connected()),
                              "wallpaper": OPT.get("wallpaper", "")})


async def post_scan(r):
    hub.scan_in_background()
    return web.json_response({"ok": True})


def net_msg(e):
    """Short text for an error from Tuya's servers."""
    if isinstance(e, requests.RequestException):
        return "Could not reach Tuya's servers. Check that Home Assistant has internet access and try again."
    return str(e)


def clean_id(t):
    return "".join(c for c in str(t or "").strip() if c.isalnum())


async def post_device(r):
    """Add a device by hand."""
    b = await r.json()
    did, key = clean_id(b.get("id")), str(b.get("key") or "").strip()
    if not did:
        return web.json_response({"ok": False, "error": "Type the device ID."}, status=400)
    if did in store.d["devices"]:
        return web.json_response({"ok": False, "error": "That device is already in the list."}, status=400)
    ver = str(b.get("version") or "auto")
    with store.lock:
        store.d["devices"][did] = {"id": did, "name": str(b.get("name") or "").strip() or did, "ip": str(b.get("ip") or "").strip(),
                                   "key": key, "version": ver if ver in VERSIONS else "auto", "enabled": True, "entities": [],
                                   "needs_inference": True, "source": "manual"}
        store.save()
    hub.start_worker(did)
    return web.json_response({"ok": True})


async def get_device(r):
    d = hub.dev(r.query.get("id", ""))
    if not d:
        raise web.HTTPNotFound()
    return web.json_response({"id": d["id"], "name": d.get("name", ""), "ip": d.get("ip", ""), "key": d.get("key", ""),
                              "version": d.get("version", "auto"), "enabled": d.get("enabled", True)})


async def post_device_update(r):
    b = await r.json()
    d = hub.dev(b.get("id", ""))
    if not d:
        return web.json_response({"ok": False, "error": "Unknown device."}, status=404)
    old = [dict(e) for e in d.get("entities", [])]
    restart = False
    with store.lock:
        for k in ("name", "ip", "key"):
            if k in b and str(b[k]).strip() != str(d.get(k, "")):
                d[k] = str(b[k]).strip()
                restart = restart or k != "name"
        if "version" in b:
            v = str(b["version"])
            v = v if v in VERSIONS else "auto"
            restart = restart or v != d.get("version")
            d["version"] = v
        if "enabled" in b:
            d["enabled"] = bool(b["enabled"])
            restart = True
        for eid, ch in (b.get("entities") or {}).items():
            e = next((x for x in d.get("entities", []) if x["id"] == eid), None)
            if e and isinstance(ch, dict):
                if "enabled" in ch:
                    e["enabled"] = bool(ch["enabled"])
                if str(ch.get("name") or "").strip():
                    e["name"] = str(ch["name"]).strip()[:60]
                if isinstance(ch.get("labels"), dict):  # friendly names for a select's options (or a vacuum's fan speeds)
                    lab = {str(k): str(v).strip()[:40] for k, v in ch["labels"].items() if str(v).strip() and str(v).strip() != str(k)}
                    if e["platform"] == "vacuum" and isinstance(e.get("fan"), dict):
                        e["fan"]["labels"] = lab
                    else:
                        e["labels"] = lab
        store.save()
    hub.publish_device(d, old)
    if restart:
        hub.start_worker(d["id"])
    return web.json_response({"ok": True})


async def post_device_delete(r):
    b = await r.json()
    did = b.get("id", "")
    with store.lock:
        d = store.d["devices"].pop(did, None)
        store.save()
    if d:
        hub.remove_device(d)
        w = hub.workers.pop(did, None)
        if w:
            w.wake()
        hub.info.pop(did, None)
        hub.dps.pop(did, None)
    return web.json_response({"ok": True})


def vac_guess(did):
    d = hub.dev(did)
    if not d:
        return None
    g = M.guess_vacuum(hub.dps.get(did) or {}, d.get("entities", []))
    cur = next((e for e in d.get("entities", []) if e["platform"] == "vacuum"), None)
    if cur:  # already set up: show what is saved
        g.update(status=cur["dp"], mode_options=(cur.get("mode") or {}).get("options", g["mode_options"]))
        for k in ("go", "power", "battery", "locate", "mode", "fan"):
            g[k] = (cur.get(k) or {}).get("dp")
        g["fan_options"] = (cur.get("fan") or {}).get("options", [])
    g["done"] = bool(cur)
    return g


async def get_vac_guess(r):
    g = vac_guess(r.query.get("id", ""))
    if g is None:
        raise web.HTTPNotFound()
    return web.json_response(g)


async def post_vacuum(r):
    """Make a device a robot vacuum: one vacuum entity from the data points the user confirmed."""
    b = await r.json()
    d = hub.dev(b.get("id", ""))
    if not d:
        return web.json_response({"ok": False, "error": "Unknown device."}, status=404)

    def num(k):
        try:
            return int(b.get(k)) if str(b.get(k) or "").strip() else None
        except ValueError:
            return None

    cfg = {k: num(k) for k in ("status", "go", "power", "mode", "battery", "fan", "locate")}
    if not cfg["status"]:
        return web.json_response({"ok": False, "error": "Type the data point number that holds the vacuum's status (usually 5)."}, status=400)
    cfg["mode_options"] = [x.strip() for x in str(b.get("mode_options") or "").split(",") if x.strip()]
    cfg["fan_options"] = [x.strip() for x in str(b.get("fan_options") or "").split(",") if x.strip()]
    sel = next((e for e in d.get("entities", []) if e["platform"] == "select" and e["dp"] == cfg["mode"]), None)
    if sel and not cfg["mode_options"]:
        cfg["mode_options"] = list(sel.get("options", []))
    old = [dict(e) for e in d.get("entities", [])]
    prev = next((e for e in old if e["platform"] == "vacuum"), None)
    spec = M.vacuum_spec(cfg)
    if prev and isinstance(prev.get("fan"), dict) and isinstance(spec.get("fan"), dict):
        spec["fan"]["labels"] = prev["fan"].get("labels", {})
    hide = {num("direction")} - {None}
    with store.lock:
        d["entities"] = M.apply_vacuum(d.get("entities", []), spec, hide)
        d["needs_inference"] = False
        store.save()
    hub.publish_device(d, old)
    return web.json_response({"ok": True})


async def post_hide_unnamed(r):
    """Turn off every entity that is just 'DP n' (data points nobody named)."""
    b = await r.json()
    d = hub.dev(b.get("id", ""))
    if not d:
        return web.json_response({"ok": False, "error": "Unknown device."}, status=404)
    old = [dict(e) for e in d.get("entities", [])]
    n = 0
    with store.lock:
        for e in d.get("entities", []):
            if e.get("enabled", True) and re.fullmatch(r"DP \d+", e["name"]):
                e["enabled"] = False
                n += 1
        store.save()
    hub.publish_device(d, old)
    return web.json_response({"ok": True, "hidden": n})


async def post_control(r):
    b = await r.json()
    ok, why = hub.command(b.get("id", ""), b.get("entity", ""), str(b.get("value", "")))
    return web.json_response({"ok": ok, "error": why})


async def post_diagnose(r):
    b = await r.json()
    res = await asyncio.get_running_loop().run_in_executor(None, diagnose, b.get("id", ""))
    return web.json_response(res)


async def post_login_qr(r):
    b = await r.json()
    code = str(b.get("user_code") or "").strip()
    if not code:
        return web.json_response({"ok": False, "error": "Type your User Code first."}, status=400)
    try:
        res = await asyncio.get_running_loop().run_in_executor(None, C.qr_start, code)
    except Exception as e:
        return web.json_response({"ok": False, "error": net_msg(e)}, status=400)
    hub.pending_qr = {"token": res["token"], "user_code": code}
    return web.json_response({"ok": True, "svg": res["svg"]})


async def get_login_poll(r):
    p = hub.pending_qr
    if not p:
        return web.json_response({"ok": False, "state": "none"})
    ok, res = await asyncio.get_running_loop().run_in_executor(None, C.qr_poll, p["token"], p["user_code"])
    if not ok:
        return web.json_response({"ok": True, "state": "waiting"})
    with store.lock:
        store.d["auth"] = res
        store.save()
    hub.pending_qr = None
    return web.json_response({"ok": True, "state": "signed_in"})


async def post_logout(r):
    with store.lock:
        store.d["auth"] = None
        store.save()
    return web.json_response({"ok": True})


def sync_cloud():
    a = store.d.get("auth")
    if not a:
        raise RuntimeError("Sign in first.")
    devs = C.fetch_devices(a, store.save)
    added = updated = skipped = 0
    for c in devs:
        if not c["key"]:
            skipped += 1  # sub-devices (Zigbee/Bluetooth behind a gateway) have no local key
            continue
        with store.lock:
            d = store.d["devices"].get(c["id"])
            new_ents = M.build_entities(c["dps"], c["category"]) if c["dps"] else None
            if d is None:
                d = {"id": c["id"], "ip": "", "version": "auto", "enabled": True, "source": "cloud", "entities": [],
                     "needs_inference": not new_ents}
                store.d["devices"][c["id"]] = d
                added += 1
            else:
                updated += 1
            old = [dict(e) for e in d.get("entities", [])]
            d.update(key=c["key"], category=c["category"], product_id=c["product_id"], product_name=c["product_name"])
            if not d.get("name") or d["name"] == d["id"]:
                d["name"] = c["name"]
            if new_ents:
                d["entities"] = M.merge_entities(d.get("entities"), new_ents)
                d["needs_inference"] = False
            store.save()
        hub.publish_device(d, old)
        hub.start_worker(c["id"])
    return {"added": added, "updated": updated, "skipped": skipped, "total": len(devs)}


async def post_cloud_sync(r):
    try:
        res = await asyncio.get_running_loop().run_in_executor(None, sync_cloud)
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Could not read your Tuya account: {net_msg(e)}"}, status=400)
    return web.json_response(dict(res, ok=True))


def do_import(text):
    if not text:
        path = os.path.join(HA_CONFIG, ".storage", "core.config_entries")
        try:
            j = json.load(open(path))
        except (OSError, ValueError) as e:
            raise RuntimeError(f"Could not read LocalTuya's saved settings ({e}). You can paste them instead.")
        ents = [e for e in (j.get("data") or {}).get("entries", []) if e.get("domain") == "localtuya"]
        if not ents:
            raise RuntimeError("LocalTuya is not set up in this Home Assistant.")
        text = json.dumps(ents)
    devs, skipped = C.parse_localtuya(text)
    if not devs:
        raise RuntimeError("No devices with a local key were found there.")
    added = 0
    for c in devs:
        with store.lock:
            d = store.d["devices"].get(c["id"])
            if d is None:
                d = dict(c, enabled=True, source="localtuya")
                store.d["devices"][c["id"]] = d
                added += 1
            else:
                for k in ("ip", "key"):
                    if not d.get(k) and c.get(k):
                        d[k] = c[k]
                if not d.get("entities") and c["entities"]:
                    d["entities"] = c["entities"]
                    d["needs_inference"] = True
            store.save()
        hub.publish_device(d)
        hub.start_worker(c["id"])
    return {"added": added, "total": len(devs), "skipped": skipped}


async def post_import(r):
    try:
        b = await r.json()
    except ValueError:
        b = {}
    try:
        res = await asyncio.get_running_loop().run_in_executor(None, do_import, str(b.get("text") or ""))
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=400)
    return web.json_response(dict(res, ok=True))


async def get_debug(r):
    return web.json_response({"sent": sent[-400:]}) if TEST else web.json_response({})


async def start_bg(app):
    hub.start_mqtt()
    hub.start_all()
    threading.Thread(target=hub.housekeeping, daemon=True).start()


app = web.Application(middlewares=[only_local], client_max_size=2 * 1024 * 1024)
app.router.add_get("/", index)
app.router.add_get("/api/state", get_state)
app.router.add_get("/api/ci", get_ci)
app.router.add_post("/api/ci/start", post_ci_start)
app.router.add_post("/api/ci/stop", post_ci_stop)
app.router.add_post("/api/scan", post_scan)
app.router.add_post("/api/device", post_device)
app.router.add_get("/api/device", get_device)
app.router.add_post("/api/device/update", post_device_update)
app.router.add_post("/api/device/delete", post_device_delete)
app.router.add_get("/api/device/vacuum", get_vac_guess)
app.router.add_post("/api/device/vacuum", post_vacuum)
app.router.add_post("/api/device/hide_unnamed", post_hide_unnamed)
app.router.add_post("/api/control", post_control)
app.router.add_post("/api/diagnose", post_diagnose)
app.router.add_post("/api/login/qr", post_login_qr)
app.router.add_get("/api/login/poll", get_login_poll)
app.router.add_post("/api/login/logout", post_logout)
app.router.add_post("/api/cloud/sync", post_cloud_sync)
app.router.add_post("/api/import", post_import)
app.router.add_get("/api/debug", get_debug)
app.on_startup.append(start_bg)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT, print=None)
