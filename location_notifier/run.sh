#!/usr/bin/with-contenv bashio
bashio::log.info "Starting Arrival Alerts"
exec python3 -u /app/main.py
