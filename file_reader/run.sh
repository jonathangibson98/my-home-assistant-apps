#!/bin/sh
set -e

CONFIG_PATH=/data/options.json

export FILES_PATH=$(jq --raw-output '.files_path // "/data/files"' $CONFIG_PATH)
export MQTT_HOST=$(jq --raw-output '.mqtt_host // "core-mosquitto"' $CONFIG_PATH)
export MQTT_PORT=$(jq --raw-output '.mqtt_port // 1883' $CONFIG_PATH)
export MQTT_USER=$(jq --raw-output '.mqtt_user // ""' $CONFIG_PATH)
export MQTT_PASS=$(jq --raw-output '.mqtt_password // ""' $CONFIG_PATH)

echo "[file_reader] Files folder: $FILES_PATH"
exec python3 -u /usr/src/app/app/app.py
