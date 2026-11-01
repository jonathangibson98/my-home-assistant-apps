import io
import json
import logging
import os
import random
import re
import signal
import threading
import urllib.request

import paho.mqtt.client as mqtt
from PIL import Image, ImageOps

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("photo_shuffle")

OPTIONS = json.load(open("/data/options.json"))
MAX_DIM = int(OPTIONS.get("max_dimension", 1920))
QUALITY = int(OPTIONS.get("jpeg_quality", 85))
EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}
DISCOVERY = "homeassistant"
BASE = "photo_shuffle"
STATUS_TOPIC = f"{BASE}/status"
KNOWN_FILE = "/data/known.json"

stop = threading.Event()
connected = threading.Event()


def slugify(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") or "shuffle"


class Shuffle:
    def __init__(self, cfg, slug):
        self.name = cfg["name"]
        self.path = cfg["path"]
        self.interval = int(cfg.get("interval", 60))
        self.recursive = bool(cfg.get("recursive", True))
        self.slug = slug
        self.deck = []
        self.last = None
        self.trigger = threading.Event()
        self.image_topic = f"{BASE}/{slug}/image"
        self.cmd_topic = f"{BASE}/{slug}/next"

    def scan(self):
        files = []
        if not os.path.isdir(self.path):
            log.warning("[%s] folder not found: %s", self.name, self.path)
            return files
        if self.recursive:
            for root, _, names in os.walk(self.path):
                for n in names:
                    if os.path.splitext(n)[1].lower() in EXTS:
                        files.append(os.path.join(root, n))
        else:
            for n in os.listdir(self.path):
                p = os.path.join(self.path, n)
                if os.path.isfile(p) and os.path.splitext(n)[1].lower() in EXTS:
                    files.append(p)
        return files

    def pick(self):
        if not self.deck:
            self.deck = self.scan()
            random.shuffle(self.deck)
            if len(self.deck) > 1 and self.deck[-1] == self.last:
                self.deck.insert(0, self.deck.pop())
        if not self.deck:
            return None
        self.last = self.deck.pop()
        return self.last

    @staticmethod
    def render(path):
        with Image.open(path) as im:
            if getattr(im, "is_animated", False):
                im.seek(0)
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((MAX_DIM, MAX_DIM), Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=QUALITY, optimize=True)
            return buf.getvalue()

    def publish_next(self, client):
        for _ in range(5):
            path = self.pick()
            if not path:
                log.warning("[%s] no pictures found in %s", self.name, self.path)
                return
            try:
                data = self.render(path)
            except Exception as e:
                log.warning("[%s] skipping %s: %s", self.name, path, e)
                continue
            client.publish(self.image_topic, data, qos=1, retain=True)
            log.info("[%s] %s", self.name, path)
            return

    def loop(self, client):
        connected.wait()
        while not stop.is_set():
            try:
                self.publish_next(client)
            except Exception:
                log.exception("[%s] error", self.name)
            self.trigger.wait(self.interval)
            self.trigger.clear()

    def discovery(self, client):
        device = {
            "identifiers": [f"{BASE}_{self.slug}"],
            "name": self.name,
            "manufacturer": "Photo Shuffle add-on",
            "model": "Folder shuffle",
        }
        avail = {"availability_topic": STATUS_TOPIC}
        image_cfg = {
            "name": None,
            "unique_id": f"{BASE}_{self.slug}_image",
            "image_topic": self.image_topic,
            "content_type": "image/jpeg",
            "device": device,
            **avail,
        }
        button_cfg = {
            "name": "Next photo",
            "unique_id": f"{BASE}_{self.slug}_next",
            "command_topic": self.cmd_topic,
            "payload_press": "PRESS",
            "device": device,
            **avail,
        }
        client.publish(f"{DISCOVERY}/image/{BASE}_{self.slug}/config", json.dumps(image_cfg), qos=1, retain=True)
        client.publish(f"{DISCOVERY}/button/{BASE}_{self.slug}_next/config", json.dumps(button_cfg), qos=1, retain=True)


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


def main():
    shuffles, seen = [], set()
    for cfg in OPTIONS.get("shuffles", []):
        base = slugify(cfg["name"])
        slug, n = base, 2
        while slug in seen:
            slug, n = f"{base}_{n}", n + 1
        seen.add(slug)
        shuffles.append(Shuffle(cfg, slug))
    by_cmd = {s.cmd_topic: s for s in shuffles}

    try:
        old = set(json.load(open(KNOWN_FILE)))
    except Exception:
        old = set()

    cfg = mqtt_settings()
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id="photo_shuffle_addon")
    except AttributeError:
        client = mqtt.Client(client_id="photo_shuffle_addon")
    if cfg.get("username"):
        client.username_pw_set(cfg["username"], cfg.get("password"))
    if cfg.get("ssl"):
        client.tls_set()
    client.will_set(STATUS_TOPIC, "offline", qos=1, retain=True)

    def on_connect(c, userdata, flags, rc):
        if rc != 0:
            log.error("MQTT connect failed: %s", rc)
            return
        log.info("Connected to MQTT")
        for slug in old - seen:  # remove entities for deleted shuffles
            c.publish(f"{DISCOVERY}/image/{BASE}_{slug}/config", "", qos=1, retain=True)
            c.publish(f"{DISCOVERY}/button/{BASE}_{slug}_next/config", "", qos=1, retain=True)
            c.publish(f"{BASE}/{slug}/image", "", qos=1, retain=True)
        for s in shuffles:
            s.discovery(c)
            c.subscribe(s.cmd_topic)
        c.publish(STATUS_TOPIC, "online", qos=1, retain=True)
        with open(KNOWN_FILE, "w") as f:
            json.dump(sorted(seen), f)
        connected.set()

    def on_disconnect(c, userdata, rc):
        connected.clear()

    def on_message(c, userdata, msg):
        s = by_cmd.get(msg.topic)
        if s:
            s.trigger.set()

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_message = on_message
    client.connect(cfg["host"], int(cfg["port"]), 60)
    client.loop_start()

    for s in shuffles:
        threading.Thread(target=s.loop, args=(client,), daemon=True).start()

    signal.signal(signal.SIGTERM, lambda *a: stop.set())
    signal.signal(signal.SIGINT, lambda *a: stop.set())
    stop.wait()
    client.publish(STATUS_TOPIC, "offline", qos=1, retain=True).wait_for_publish(2)
    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()
