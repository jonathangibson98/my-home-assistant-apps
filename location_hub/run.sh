#!/usr/bin/with-contenv bashio
bashio::log.info "Starting Location Hub"
exec python3 -u /app/main.py
