#!/usr/bin/with-contenv bashio
bashio::log.info "Starting AI Builder..."
exec python3 -u /app/main.py
