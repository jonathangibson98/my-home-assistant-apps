#!/usr/bin/env bash
set -e

CONFIG_PATH="/data/options.json"

# Read options from Home Assistant config
USERNAME=$(jq --raw-output ".username" $CONFIG_PATH)
PASSWORD=$(jq --raw-output ".password" $CONFIG_PATH)
SCAN_INTERVAL=$(jq --raw-output ".scan_interval" $CONFIG_PATH)

echo "[Info] Starting iCloud Lite Add-on..."

# Export environment variables for your python script to read
export ICLOUD_USERNAME="$USERNAME"
export ICLOUD_PASSWORD="$PASSWORD"
export SCAN_INTERVAL="$SCAN_INTERVAL"
export SUPERVISOR_TOKEN="$SUPERVISOR_TOKEN"

# Run your main python script
python3 -m icloud_lite.main
