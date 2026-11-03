#!/usr/bin/with-contenv bashio
bashio::log.info "Starting AI Builder (with Announcement Maker)..."
exec python3 -u /app/main.py
