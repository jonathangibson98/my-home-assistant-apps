#!/usr/bin/env bash
set -e

CONFIG_PATH="/data/options.json"

# Read user settings from Home Assistant
USERNAME=$(jq --raw-output ".username" $CONFIG_PATH)
PASSWORD=$(jq --raw-output ".password" $CONFIG_PATH)

echo "[Info] Starting iCloud Lite..."

# Export them as environment variables for Python
export ICLOUD_USERNAME="$USERNAME"
export ICLOUD_PASSWORD="$PASSWORD"

# Run your python script
python3 main.py
