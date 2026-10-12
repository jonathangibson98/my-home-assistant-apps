#!/usr/bin/with-contenv bashio
bashio::log.info "Starting iCloud Lite..."
exec /venv/bin/python3 /app/main.py
