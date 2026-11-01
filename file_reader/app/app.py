import os
import json
import logging
import paho.mqtt.client as mqtt
from flask import Flask, render_template, request, jsonify

logging.basicConfig(level=logging.INFO)

app = Flask(__name__)
DATA_DIR = "/data/files"

MQTT_HOST = os.getenv("MQTT_HOST") or "core-mosquitto"
mqtt_port_raw = os.getenv("MQTT_PORT")
MQTT_PORT = int(mqtt_port_raw) if mqtt_port_raw and mqtt_port_raw.isdigit() else 1883
MQTT_USER = os.getenv("MQTT_USER") or ""
MQTT_PASS = os.getenv("MQTT_PASS") or ""

mqtt_client = mqtt.Client(client_id="file_reader_addon")

if MQTT_USER:
    mqtt_client.username_pw_set(MQTT_USER, MQTT_PASS)

def connect_mqtt():
    try:
        mqtt_client.connect(MQTT_HOST, MQTT_PORT, 60)
        mqtt_client.loop_start()
        logging.info("Connected to MQTT Broker.")
    except Exception as e:
        logging.error(f"Failed to connect to MQTT broker: {e}")

connect_mqtt()

def publish_mqtt_discovery(filename):
    safe_name = filename.replace('.', '_').replace('-', '_')
    discovery_topic = f"homeassistant/sensor/file_reader/{safe_name}/config"
    state_topic = f"file_reader/sensor/{safe_name}/state"
    attr_topic = f"file_reader/sensor/{safe_name}/attributes"

    file_path = os.path.join(DATA_DIR, filename)
    content = ""
    lines = []
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.splitlines()

    payload = {
        "name": f"File Reader {filename}",
        "unique_id": f"file_reader_{safe_name}",
        "state_topic": state_topic,
        "json_attributes_topic": attr_topic,
        "icon": "mdi:file-text",
        "device": {
            "identifiers": ["file_reader_addon"],
            "name": "File Reader Storage Engine",
            "model": "File Reader MQTT Add-on",
            "manufacturer": "Home Assistant Add-on"
        }
    }
    
    mqtt_client.publish(discovery_topic, json.dumps(payload), retain=True)

    state_val = lines[-1] if lines else "Empty"
    if len(state_val) > 255:
        state_val = state_val[:252] + "..."

    mqtt_client.publish(state_topic, state_val, retain=True)
    mqtt_client.publish(attr_topic, json.dumps({"content": content, "line_count": len(lines)}), retain=True)

def sync_all_files():
    if os.path.exists(DATA_DIR):
        for fname in os.listdir(DATA_DIR):
            if os.path.isfile(os.path.join(DATA_DIR, fname)):
                publish_mqtt_discovery(fname)

sync_all_files()

@app.route('/')
def index():
    files = []
    if os.path.exists(DATA_DIR):
        files = [f for f in os.listdir(DATA_DIR) if os.path.isfile(os.path.join(DATA_DIR, f))]
    return render_template('index.html', files=files)

@app.route('/api/files', methods=['GET'])
def list_files():
    files = [f for f in os.listdir(DATA_DIR) if os.path.isfile(os.path.join(DATA_DIR, f))]
    return jsonify({"files": files})

@app.route('/api/file/<filename>', methods=['GET'])
def read_file(filename):
    file_path = os.path.join(DATA_DIR, filename)
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as f:
            return jsonify({"filename": filename, "content": f.read()})
    return jsonify({"error": "File not found"}), 404

@app.route('/api/file/<filename>', methods=['POST'])
def write_file(filename):
    data = request.get_json(force=True, silent=True) or {}
    text = data.get("text", "")
    mode = data.get("mode", "append")

    file_path = os.path.join(DATA_DIR, filename)
    file_mode = "a" if mode == "append" else "w"
    
    with open(file_path, file_mode, encoding="utf-8") as f:
        if mode == "append" and os.path.exists(file_path) and os.path.getsize(file_path) > 0:
            f.write("\n" + text)
        else:
            f.write(text)

    publish_mqtt_discovery(filename)
    return jsonify({"status": "success", "filename": filename})

@app.route('/api/file/<filename>', methods=['DELETE'])
def delete_file(filename):
    file_path = os.path.join(DATA_DIR, filename)
    if os.path.exists(file_path):
        os.remove(file_path)
        safe_name = filename.replace('.', '_').replace('-', '_')
        mqtt_client.publish(f"homeassistant/sensor/file_reader/{safe_name}/config", "", retain=True)
        return jsonify({"status": "deleted"})
    return jsonify({"error": "File not found"}), 404

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8099)
