import collections
import io
import json
import logging
import os
import random
import re
import signal
import threading
import time
import urllib.request

import paho.mqtt.client as mqtt
from flask import Flask, Response, jsonify, request
from PIL import Image, ImageOps

DATA_DIR = os.environ.get("PS_DATA_DIR", "/data")
HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------- logging
class UILog(logging.Handler):
    """Keeps recent log lines so the web UI can show what the add-on is doing."""

    def __init__(self):
        super().__init__()
        self.buf = collections.deque(maxlen=300)

    def emit(self, record):
        self.buf.append({"t": int(record.created), "l": record.levelname, "m": record.getMessage()})


UI_LOG = UILog()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger().addHandler(UI_LOG)
logging.getLogger("werkzeug").setLevel(logging.WARNING)
log = logging.getLogger("photo_shuffle")

# ---------------------------------------------------------------- options
OPTIONS = json.load(open(os.path.join(DATA_DIR, "options.json")))
MAX_DIM = int(OPTIONS.get("max_dimension", 1920))
QUALITY = int(OPTIONS.get("jpeg_quality", 85))

FORMAT_EXT = {
    "jpg": (".jpg", ".jpeg"),
    "png": (".png",),
    "webp": (".webp",),
    "gif": (".gif",),
    "bmp": (".bmp",),
    "tiff": (".tif", ".tiff"),
}
FORMATS = [f for f in (OPTIONS.get("formats") or []) if f in FORMAT_EXT]
if not FORMATS:
    FORMATS = ["jpg", "png", "webp"]
    log.warning("No picture formats selected, using jpg, png and webp")
EXTS = {e for f in FORMATS for e in FORMAT_EXT[f]}

ROOTS = []
for _p in OPTIONS.get("photo_paths") or []:
    _p = os.path.normpath(str(_p).strip())
    if _p.startswith("/") and _p not in ROOTS:
        ROOTS.append(_p)

DISCOVERY = "homeassistant"
BASE = "photo_shuffle"
STATUS_TOPIC = f"{BASE}/status"

# One shared Home Assistant device that holds every shuffle's image entity
DEVICE = {
    "identifiers": [BASE],
    "name": "Photo Shuffle",
    "manufacturer": "Photo Shuffle add-on",
    "model": "Folder shuffle",
}
STORE = os.path.join(DATA_DIR, "shuffles.json")
DEVICE_REV = 2  # 2 = every shuffle lives on the shared "Photo Shuffle" device

stop = threading.Event()
CONNECTED = threading.Event()
mq_state = {"status": "starting", "detail": ""}


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "shuffle"


def in_roots(path):
    rp = os.path.realpath(path)
    for r in ROOTS:
        rr = os.path.realpath(r)
        if rp == rr or rp.startswith(rr + os.sep):
            return True
    return False


def is_image(name):
    return not name.startswith(".") and os.path.splitext(name)[1].lower() in EXTS


def render(path):
    """Return (full-size jpeg bytes, small preview jpeg bytes)."""
    with Image.open(path) as im:
        if im.format == "JPEG":
            im.draft("RGB", (MAX_DIM, MAX_DIM))
        if getattr(im, "is_animated", False):
            im.seek(0)
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((MAX_DIM, MAX_DIM), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=QUALITY, optimize=True)
        th = im.copy()
        th.thumbnail((480, 480), Image.Resampling.LANCZOS)
        tb = io.BytesIO()
        th.save(tb, "JPEG", quality=70)
        return buf.getvalue(), tb.getvalue()


# ---------------------------------------------------------------- shuffle
class Shuffle:
    def __init__(self, sid, cfg):
        self.id = sid
        self.name = cfg["name"]
        self.path = cfg["path"]
        self.interval = int(cfg["interval"])
        self.recursive = bool(cfg["recursive"])
        self.enabled = bool(cfg["enabled"])
        self.lock = threading.Lock()
        self.deck = []
        self.last = None
        self.current = None
        self.thumb = None
        self.changed_at = None
        self.next_at = None
        self.count = None
        self.error = None
        self.trigger = threading.Event()
        self.stop_ev = threading.Event()
        self.thread = None
        self.image_topic = f"{BASE}/{sid}/image"
        self.seq = 0
        self.cond = threading.Condition()

    def cfg(self):
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "interval": self.interval,
            "recursive": self.recursive,
            "enabled": self.enabled,
        }

    def view(self):
        d = self.cfg()
        d.update(
            count=self.count,
            current=self.current,
            changed_at=self.changed_at,
            next_at=self.next_at,
            error=self.error,
            has_image=self.thumb is not None,
        )
        return d

    def scan(self):
        files = []
        if not os.path.isdir(self.path):
            self.error = "Folder not found"
            self.count = 0
            return files
        if not in_roots(self.path):
            self.error = "Folder is outside the allowed photo paths"
            self.count = 0
            return files
        if self.recursive:
            for root, dirs, names in os.walk(self.path):
                dirs[:] = [d for d in dirs if not d.startswith(".")]
                files.extend(os.path.join(root, n) for n in names if is_image(n))
        else:
            with os.scandir(self.path) as it:
                files = [e.path for e in it if e.is_file() and is_image(e.name)]
        self.count = len(files)
        if not files:
            self.error = "No pictures found (formats: %s)" % ", ".join(FORMATS)
        return files

    def reset_deck(self):
        with self.lock:
            self.deck = []

    def pick(self):
        with self.lock:
            if not self.deck:
                self.deck = self.scan()
                random.shuffle(self.deck)
                if len(self.deck) > 1 and self.deck[-1] == self.last:
                    self.deck.insert(0, self.deck.pop())
            if not self.deck:
                return None
            self.last = self.deck.pop()
            return self.last

    def publish_next(self):
        for _ in range(5):
            path = self.pick()
            if not path:
                if self.error and self.error != getattr(self, "_logged_error", None):
                    log.warning("%s: %s (%s)", self.name, self.error, self.path)
                    self._logged_error = self.error
                return False
            try:
                full, thumb = render(path)
            except Exception as e:
                log.warning("%s: skipping %s (%s)", self.name, path, e)
                continue
            mgr.publish(self.image_topic, full)
            self.thumb = thumb
            self.changed_at = time.time()
            self.error = None
            self._logged_error = None
            try:
                self.current = os.path.relpath(path, self.path)
            except ValueError:
                self.current = os.path.basename(path)
            log.info("%s: now showing %s", self.name, self.current)
            return True
        self.error = "Could not read any of the pictures"
        return False

    def request_next(self, wait=15):
        """Pick a new photo right now. Returns once it has been published (or failed)."""
        with self.cond:
            before = self.seq
        self.trigger.set()
        with self.cond:
            self.cond.wait_for(lambda: self.seq != before, timeout=wait)

    def loop(self):
        while not self.stop_ev.is_set():
            forced = self.trigger.is_set()
            self.trigger.clear()
            if not CONNECTED.is_set():
                self.next_at = None
                CONNECTED.wait(3)
                # a Next press while MQTT was down must not hang the UI
                with self.cond:
                    self.seq += 1
                    self.cond.notify_all()
                continue
            if self.enabled or forced:
                try:
                    self.publish_next()
                except Exception:
                    log.exception("%s: unexpected error", self.name)
                with self.cond:
                    self.seq += 1
                    self.cond.notify_all()
            if self.stop_ev.is_set():
                break
            if self.enabled:
                self.next_at = time.time() + self.interval
                self.trigger.wait(self.interval)
            else:
                self.next_at = None
                self.trigger.wait(3600)

    def start(self):
        self.thread = threading.Thread(target=self.loop, daemon=True)
        self.thread.start()

    def halt(self):
        self.stop_ev.set()
        self.trigger.set()

    def discovery(self, client):
        image_cfg = {
            "name": self.name,
            "unique_id": f"{BASE}_{self.id}_image",
            "default_entity_id": f"image.{self.id}",
            "image_topic": self.image_topic,
            "content_type": "image/jpeg",
            "availability_topic": STATUS_TOPIC,
            "device": DEVICE,
        }
        client.publish(f"{DISCOVERY}/image/{BASE}_{self.id}/config", json.dumps(image_cfg), qos=1, retain=True)


# ---------------------------------------------------------------- manager
class Manager:
    def __init__(self):
        self.lock = threading.RLock()
        self.shuffles = {}
        self.removed = []
        self.device_rev = DEVICE_REV
        self.client = None

    # persistence
    def load(self):
        data = None
        try:
            with open(STORE) as f:
                data = json.load(f)
        except FileNotFoundError:
            legacy = OPTIONS.get("shuffles")
            if legacy:
                log.info("Importing %d shuffle(s) from the old configuration", len(legacy))
                data = {"shuffles": []}
                for item in legacy:
                    data["shuffles"].append(
                        {
                            "id": slugify(item["name"]),
                            "name": item["name"],
                            "path": item["path"],
                            "interval": item.get("interval", 60),
                            "recursive": item.get("recursive", True),
                            "enabled": True,
                        }
                    )
        except Exception as e:
            log.error("Could not read %s: %s", STORE, e)
        data = data or {}
        for c in data.get("shuffles", []):
            try:
                self.shuffles[c["id"]] = Shuffle(c["id"], c)
            except Exception as e:
                log.warning("Skipping bad shuffle entry: %s", e)
        self.removed = list(data.get("removed", []))
        # stores written before the shared device existed have no device_rev and need a one-time move
        self.device_rev = data.get("device_rev", 0 if self.shuffles else DEVICE_REV)
        self.save()

    def save(self):
        with self.lock:
            data = {"shuffles": [s.cfg() for s in self.shuffles.values()], "removed": self.removed, "device_rev": self.device_rev}
            tmp = STORE + ".tmp"
            with open(tmp, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, STORE)

    def all(self):
        with self.lock:
            return list(self.shuffles.values())

    def get(self, sid):
        with self.lock:
            return self.shuffles.get(sid)

    # mqtt helpers
    def publish(self, topic, payload, retain=True):
        if self.client is not None and CONNECTED.is_set():
            self.client.publish(topic, payload, qos=1, retain=retain)

    def purge_removed(self):
        if self.client is None or not CONNECTED.is_set():
            return
        with self.lock:
            for sid in self.removed:
                if sid in self.shuffles:
                    continue
                self.client.publish(f"{DISCOVERY}/image/{BASE}_{sid}/config", "", qos=1, retain=True)
                self.client.publish(f"{DISCOVERY}/button/{BASE}_{sid}_next/config", "", qos=1, retain=True)
                self.client.publish(f"{BASE}/{sid}/image", "", qos=1, retain=True)
                log.info("Removed Home Assistant entities for '%s'", sid)
            self.removed = []
            self.save()

    def announce(self, s):
        if self.client is not None and CONNECTED.is_set():
            s.discovery(self.client)

    # operations
    def validate(self, data, current=None):
        name = str(data.get("name", "")).strip()[:40]
        if not name:
            raise ValueError("Give the shuffle a name")
        for s in self.all():
            if s.name.lower() == name.lower() and (current is None or s.id != current.id):
                raise ValueError("A shuffle called '%s' already exists" % name)
        path = str(data.get("path", "")).strip()
        if not path.startswith("/"):
            raise ValueError("Choose a folder")
        path = os.path.normpath(path)
        if not ROOTS:
            raise ValueError("No photo paths are set. Add some in the add-on Configuration tab")
        if not in_roots(path):
            raise ValueError("Folder must be inside an allowed photo path: " + ", ".join(ROOTS))
        if not os.path.isdir(path):
            raise ValueError("That folder does not exist")
        try:
            interval = int(data.get("interval", 60))
        except (TypeError, ValueError):
            raise ValueError("Interval must be a number of seconds")
        if not 5 <= interval <= 86400:
            raise ValueError("Interval must be between 5 seconds and 24 hours")
        return {
            "name": name,
            "path": path,
            "interval": interval,
            "recursive": bool(data.get("recursive", True)),
            "enabled": bool(data.get("enabled", True)),
        }

    def add(self, data):
        cfg = self.validate(data)
        with self.lock:
            base = slugify(cfg["name"])
            sid, n = base, 2
            while sid in self.shuffles:
                sid, n = f"{base}_{n}", n + 1
            s = Shuffle(sid, cfg)
            self.shuffles[sid] = s
            if sid in self.removed:
                self.removed.remove(sid)
            self.save()
        self.announce(s)
        s.start()
        log.info("Added shuffle '%s' (%s)", s.name, s.path)
        return s

    def update(self, sid, data):
        s = self.get(sid)
        if s is None:
            raise KeyError(sid)
        cfg = self.validate({**s.cfg(), **data}, current=s)
        with self.lock:
            reset = (cfg["path"], cfg["recursive"]) != (s.path, s.recursive)
            renamed = cfg["name"] != s.name
            s.name, s.path = cfg["name"], cfg["path"]
            s.interval, s.recursive, s.enabled = cfg["interval"], cfg["recursive"], cfg["enabled"]
            self.save()
        if reset:
            s.reset_deck()
        if renamed:
            self.announce(s)
        if s.enabled or reset:
            s.trigger.set()
        log.info("Updated shuffle '%s'", s.name)
        return s

    def delete(self, sid):
        with self.lock:
            s = self.shuffles.pop(sid, None)
            if s is None:
                raise KeyError(sid)
            s.halt()
            if sid not in self.removed:
                self.removed.append(sid)
            self.save()
        log.info("Deleted shuffle '%s'", s.name)
        self.purge_removed()


mgr = Manager()


# ---------------------------------------------------------------- mqtt
def mqtt_settings():
    if OPTIONS.get("mqtt_host"):
        return {
            "host": OPTIONS["mqtt_host"],
            "port": int(OPTIONS.get("mqtt_port") or 1883),
            "username": OPTIONS.get("mqtt_username") or None,
            "password": OPTIONS.get("mqtt_password") or None,
            "ssl": False,
        }
    req = urllib.request.Request(
        "http://supervisor/services/mqtt",
        headers={"Authorization": f"Bearer {os.environ.get('SUPERVISOR_TOKEN', '')}"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.load(r)["data"]


def migrate_devices(c):
    """Home Assistant never moves an existing MQTT entity to another device.
    Remove each entity once, then announce it again on the shared device.
    Entity IDs are kept because the discovery payload sets default_entity_id."""
    shuffles = mgr.all()
    log.info(
        "Moving %d shuffle(s) onto the shared 'Photo Shuffle' device. Their entities are re-created once, entity IDs stay the same",
        len(shuffles),
    )
    for s in shuffles:
        c.publish(f"{DISCOVERY}/image/{BASE}_{s.id}/config", "", qos=1, retain=True)
        c.publish(f"{DISCOVERY}/button/{BASE}_{s.id}_next/config", "", qos=1, retain=True)
    if stop.wait(8) or not CONNECTED.is_set():
        log.warning("Device move interrupted, it will be retried on the next connect")
        return
    for s in mgr.all():
        s.discovery(c)
        s.trigger.set()  # publish a fresh picture so the new entity is not empty
    mgr.device_rev = DEVICE_REV
    mgr.save()
    log.info("Device move finished")


def mqtt_worker():
    cfg = None
    while not stop.is_set():
        try:
            cfg = mqtt_settings()
            break
        except Exception as e:
            mq_state.update(status="error", detail="No MQTT broker found. Is the Mosquitto add-on running?")
            log.error("Could not get MQTT settings (%s). Retrying in 15s", e)
            stop.wait(15)
    if cfg is None:
        return
    log.info("Using MQTT broker %s:%s", cfg["host"], cfg["port"])
    mq_state.update(status="connecting", detail="%s:%s" % (cfg["host"], cfg["port"]))

    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="photo_shuffle_addon")
    except AttributeError:
        client = mqtt.Client(client_id="photo_shuffle_addon")
    if cfg.get("username"):
        client.username_pw_set(cfg["username"], cfg.get("password"))
    if cfg.get("ssl"):
        client.tls_set()
    client.will_set(STATUS_TOPIC, "offline", qos=1, retain=True)
    client.reconnect_delay_set(min_delay=2, max_delay=30)

    def on_connect(c, userdata, flags, rc):
        if rc != 0:
            mq_state.update(status="error", detail="Broker refused the connection (code %s)" % rc)
            log.error("MQTT connect failed: %s", rc)
            return
        log.info("Connected to MQTT")
        mq_state.update(status="connected", detail="%s:%s" % (cfg["host"], cfg["port"]))
        c.publish(STATUS_TOPIC, "online", qos=1, retain=True)
        CONNECTED.set()
        if mgr.device_rev < DEVICE_REV:
            threading.Thread(target=migrate_devices, args=(c,), daemon=True).start()
        else:
            for s in mgr.all():
                s.discovery(c)
        mgr.purge_removed()

    def on_disconnect(c, userdata, rc):
        CONNECTED.clear()
        mq_state.update(status="connecting", detail="Reconnecting to %s:%s" % (cfg["host"], cfg["port"]))
        if not stop.is_set():
            log.warning("Lost MQTT connection, reconnecting")

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    mgr.client = client
    try:
        client.connect_async(cfg["host"], int(cfg["port"]), 60)
        client.loop_start()
    except Exception as e:
        mq_state.update(status="error", detail=str(e))
        log.error("MQTT start failed: %s", e)


# ---------------------------------------------------------------- web ui
app = Flask(__name__)
INDEX = open(os.path.join(HERE, "index.html"), encoding="utf-8").read()


@app.before_request
def only_ingress():
    if os.environ.get("PS_DEV"):
        return None
    if request.remote_addr not in ("172.30.32.2", "127.0.0.1"):
        return Response("Forbidden", 403)


def err(msg, code=400):
    return jsonify({"error": msg}), code


@app.get("/")
def index():
    return Response(INDEX, mimetype="text/html", headers={"Cache-Control": "no-store"})


@app.get("/api/state")
def api_state():
    return jsonify(
        {
            "now": time.time(),
            "mqtt": dict(mq_state),
            "formats": FORMATS,
            "max_dimension": MAX_DIM,
            "roots": [{"path": r, "exists": os.path.isdir(r)} for r in ROOTS],
            "shuffles": [s.view() for s in mgr.all()],
            "log": list(UI_LOG.buf)[-80:],
        }
    )


@app.post("/api/shuffles")
def api_add():
    try:
        s = mgr.add(request.get_json(silent=True) or {})
    except ValueError as e:
        return err(str(e))
    return jsonify(s.view())


@app.put("/api/shuffles/<sid>")
def api_update(sid):
    try:
        s = mgr.update(sid, request.get_json(silent=True) or {})
    except KeyError:
        return err("Not found", 404)
    except ValueError as e:
        return err(str(e))
    return jsonify(s.view())


@app.delete("/api/shuffles/<sid>")
def api_delete(sid):
    try:
        mgr.delete(sid)
    except KeyError:
        return err("Not found", 404)
    return jsonify({"ok": True})


@app.post("/api/shuffles/<sid>/next")
def api_next(sid):
    s = mgr.get(sid)
    if s is None:
        return err("Not found", 404)
    s.request_next()
    return jsonify({"ok": True})


@app.get("/api/shuffles/<sid>/thumb.jpg")
def api_thumb(sid):
    s = mgr.get(sid)
    if s is None or s.thumb is None:
        return Response(status=404)
    return Response(s.thumb, mimetype="image/jpeg", headers={"Cache-Control": "no-cache"})


@app.get("/api/browse")
def api_browse():
    p = request.args.get("path", "")
    if not p:
        return jsonify({"roots": [{"path": r, "exists": os.path.isdir(r)} for r in ROOTS]})
    p = os.path.normpath(p)
    if not in_roots(p) or not os.path.isdir(p):
        return err("Not an allowed folder")
    dirs, images = [], 0
    try:
        with os.scandir(p) as it:
            for e in it:
                if e.name.startswith("."):
                    continue
                if e.is_dir():
                    dirs.append({"name": e.name, "path": os.path.join(p, e.name)})
                elif e.is_file() and is_image(e.name):
                    images += 1
    except OSError as e:
        return err(str(e))
    dirs.sort(key=lambda d: d["name"].lower())
    parent = None if p in ROOTS else os.path.dirname(p)
    return jsonify({"path": p, "parent": parent, "dirs": dirs, "images": images})


# ---------------------------------------------------------------- main
def main():
    if not ROOTS:
        log.warning("No photo paths configured. Add some under Configuration, then restart")
    log.info("Allowed paths: %s | formats: %s", ", ".join(ROOTS) or "none", ", ".join(FORMATS))
    mgr.load()
    log.info("Loaded %d shuffle(s)", len(mgr.shuffles))
    for s in mgr.all():
        s.start()
    threading.Thread(target=mqtt_worker, daemon=True).start()
    threading.Thread(
        target=lambda: app.run(host="0.0.0.0", port=int(os.environ.get("PS_PORT", 8099)), threaded=True, use_reloader=False),
        daemon=True,
    ).start()

    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    signal.signal(signal.SIGINT, lambda *a: stop.set())
    stop.wait()
    if mgr.client is not None:
        try:
            mgr.client.publish(STATUS_TOPIC, "offline", qos=1, retain=True).wait_for_publish(2)
            mgr.client.loop_stop()
            mgr.client.disconnect()
        except Exception:
            pass


if __name__ == "__main__":
    main()
