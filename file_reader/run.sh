#!/bin/sh
set -e

CONFIG_PATH=/data/options.json

export MQTT_HOST=$(jq --raw-output '.mqtt_host // "core-mosquitto"' $CONFIG_PATH)
export MQTT_PORT=$(jq --raw-output '.mqtt_port // 1883' $CONFIG_PATH)
export MQTT_USER=$(jq --raw-output '.mqtt_user // ""' $CONFIG_PATH)
export MQTT_PASS=$(jq --raw-output '.mqtt_password // ""' $CONFIG_PATH)

mkdir -p /data/files

exec python3 /usr/src/app/app/app.py
