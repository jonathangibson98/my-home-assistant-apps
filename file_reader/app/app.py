import os
import re
import json
import shutil
import logging
import paho.mqtt.client as mqtt
from flask import Flask, render_template, request, jsonify, Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("file_reader")

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LEGACY_DIR = "/data/files"
MAPPED_ROOTS = ("/data", "/share", "/media", "/homeassistant", "/config")
MAX_ATTR_CHARS = 8000          # keep MQTT attributes small enough for Home Assistant
SKIP_NAMES = {"secrets.yaml"}  # never expose these, even if they sit in the folder


# ---------------------------------------------------------------- storage
def prepare_dir():
    wanted = os.path.abspath(os.getenv("FILES_PATH") or LEGACY_DIR)
    if not wanted.startswith(MAPPED_ROOTS):
        log.warning("%s is not in a mapped folder, files may be lost on rebuild.", wanted)
    try:
        os.makedirs(wanted, exist_ok=True)
        if not os.access(wanted, os.W_OK):
            raise PermissionError("not writable")
        return wanted
    except Exception as e:
        log.error("Cannot use %s (%s). Falling back to %s", wanted, e, LEGACY_DIR)
        os.makedirs(LEGACY_DIR, exist_ok=True)
        return LEGACY_DIR


DATA_DIR = prepare_dir()


def migrate_legacy_files():
    """One-time copy of files from the old /data/files into a newly chosen folder."""
    marker = "/data/.migrated_to"
    if DATA_DIR == LEGACY_DIR or not os.path.isdir(LEGACY_DIR):
        return
    if os.path.exists(marker) and open(marker).read().strip() == DATA_DIR:
        return
    copied = 0
    for name in os.listdir(LEGACY_DIR):
        src, dst = os.path.join(LEGACY_DIR, name), os.path.join(DATA_DIR, name)
        if os.path.isfile(src) and not os.path.exists(dst):
            shutil.copy2(src, dst)
            copied += 1
    try:
        with open(marker, "w") as f:
            f.write(DATA_DIR)
    except OSError:
        pass
    if copied:
        log.info("Copied %d existing file(s) from %s to %s", copied, LEGACY_DIR, DATA_DIR)


migrate_legacy_files()


def resolve(name):
    """Return a safe absolute path inside DATA_DIR, or None if the name is not allowed."""
    try:
        if not name or name in (".", "..") or name.lower() in SKIP_NAMES:
            return None
        root = os.path.realpath(DATA_DIR)
        path = os.path.realpath(os.path.join(DATA_DIR, name))
        return path if os.path.dirname(path) == root else None
    except ValueError:
        return None


def list_files():
    if not os.path.isdir(DATA_DIR):
        return []
    return sorted(
        f for f in os.listdir(DATA_DIR)
        if os.path.isfile(os.path.join(DATA_DIR, f))
        and not f.startswith(".") and f.lower() not in SKIP_NAMES
    )


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


# ---------------------------------------------------------------- MQTT
MQTT_HOST = os.getenv("MQTT_HOST") or "core-mosquitto"
_port = os.getenv("MQTT_PORT")
MQTT_PORT = int(_port) if _port and _port.isdigit() else 1883
MQTT_USER = os.getenv("MQTT_USER") or ""
MQTT_PASS = os.getenv("MQTT_PASS") or ""


def make_client():
    try:  # paho-mqtt 2.x
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="file_reader_addon")
    except AttributeError:  # paho-mqtt 1.x
        return mqtt.Client(client_id="file_reader_addon")


mqtt_client = make_client()
if MQTT_USER:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)


def safe_name(filename):
    return re.sub(r"[^A-Za-z0-9_]", "_", filename)


def topics(filename):
    s = safe_name(filename)
    return (
        f"homeassistant/sensor/file_reader/{s}/config",
        f"file_reader/sensor/{s}/state",
        f"file_reader/sensor/{s}/attributes",
        s,
    )


def publish_mqtt_discovery(filename):
    path = resolve(filename)
    if not path:
        return
    discovery_topic, state_topic, attr_topic, s = topics(filename)

    content = read_text(path) if os.path.exists(path) else ""
    lines = content.splitlines()

    payload = {
        "name": f"File Reader {filename}",
        "unique_id": f"file_reader_{s}",
        "state_topic": state_topic,
        "json_attributes_topic": attr_topic,
        "icon": "mdi:file-text",
        "device": {
            "identifiers": ["file_reader_addon"],
            "name": "File Reader Storage Engine",
            "model": "File Reader MQTT Add-on",
            "manufacturer": "Home Assistant Add-on",
        },
    }
    mqtt_client.publish(discovery_topic, json.dumps(payload), retain=True)

    state_val = lines[-1] if lines else "Empty"
    if len(state_val) > 255:
        state_val = state_val[:252] + "..."
    mqtt_client.publish(state_topic, state_val, retain=True)

    truncated = len(content) > MAX_ATTR_CHARS
    attrs = {
        "content": content[-MAX_ATTR_CHARS:] if truncated else content,
        "line_count": len(lines),
        "truncated": truncated,
    }
    mqtt_client.publish(attr_topic, json.dumps(attrs), retain=True)


def sync_all_files():
    for fname in list_files():
        try:
            publish_mqtt_discovery(fname)
        except Exception as e:
            log.error("Could not sync %s: %s", fname, e)


def on_connect(client, userdata, flags, reason_code, properties=None):
    failed = reason_code.is_failure if hasattr(reason_code, "is_failure") else reason_code != 0
    if failed:
        log.error("MQTT connection refused: %s", reason_code)
        return
    log.info("Connected to MQTT broker at %s:%s", MQTT_HOST, MQTT_PORT)
    sync_all_files()


def on_disconnect(client, userdata, *args):
    log.warning("Disconnected from MQTT broker, will keep retrying.")


mqtt_client.on_connect = on_connect
mqtt_client.on_disconnect = on_disconnect
mqtt_client.reconnect_delay_set(min_delay=1, max_delay=60)
try:
    mqtt_client.connect_async(MQTT_HOST, MQTT_PORT, 60)  # retries until the broker is up
    mqtt_client.loop_start()
except Exception as e:
    log.error("MQTT setup failed: %s", e)


# ---------------------------------------------------------------- web
def read_changelog():
    for p in ("/usr/src/app/CHANGELOG.md", os.path.join(BASE_DIR, "..", "CHANGELOG.md")):
        if os.path.exists(p):
            return read_text(p)
    return "No changelog found."


def current_version():
    m = re.search(r"^##\s+\[?v?(\d+(?:\.\d+)*)", read_changelog(), re.M)
    return m.group(1) if m else "unknown"


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/info", methods=["GET"])
def info():
    return jsonify({"version": current_version(), "files_path": DATA_DIR,
                    "mqtt_connected": mqtt_client.is_connected()})


@app.route("/api/changelog", methods=["GET"])
def changelog():
    return Response(read_changelog(), mimetype="text/plain")


@app.route("/api/files", methods=["GET"])
def api_list_files():
    return jsonify({"files": list_files()})


@app.route("/api/file/<filename>", methods=["GET"])
def read_file(filename):
    path = resolve(filename)
    if path and os.path.isfile(path):
        return jsonify({"filename": filename, "content": read_text(path)})
    return jsonify({"error": "File not found"}), 404


@app.route("/api/file/<filename>", methods=["POST"])
def write_file(filename):
    path = resolve(filename)
    if not path:
        return jsonify({"error": "Invalid file name"}), 400
    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text", "")
    mode = data.get("mode", "append")
    if not isinstance(text, str) or mode not in ("append", "overwrite"):
        return jsonify({"error": "Bad request"}), 400

    had_content = os.path.exists(path) and os.path.getsize(path) > 0
    with open(path, "a" if mode == "append" else "w", encoding="utf-8") as f:
        f.write(("\n" + text) if (mode == "append" and had_content) else text)

    publish_mqtt_discovery(filename)
    return jsonify({"status": "success", "filename": filename})


@app.route("/api/file/<filename>", methods=["DELETE"])
def delete_file(filename):
    path = resolve(filename)
    if path and os.path.isfile(path):
        os.remove(path)
        for t in topics(filename)[:3]:  # remove sensor config, state and attributes
            mqtt_client.publish(t, "", retain=True)
        return jsonify({"status": "deleted"})
    return jsonify({"error": "File not found"}), 404


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8099)
