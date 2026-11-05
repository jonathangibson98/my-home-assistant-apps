# Location Hub

A location history map for Home Assistant, plus everyone's location sensor, clickable switches, device trackers, a dashboard card generator and AI arrival alerts. One add-on, one sidebar entry.

**Map**
- Live map of your people and device trackers, styled like the HA map, with dark mode after sunset
- History trails, heatmap, and a playback scrubber
- Automatic stop detection and a day timeline (distance, time, average speed)
- Named places plus your HA zones, with time-at-place stats
- Follows Home Assistant's pictures and icons, with every icon set you have (all MDI, `local:` SVGs, Auto Custom Icons) and a searchable picker
- Import Google Takeout / GPX / GeoJSON / OwnTracks / CSV, backfill from HA history, export GPX/CSV/JSON
- Separate read-only map URL to embed on a dashboard, and an ingest API for OwnTracks, Overland and plain JSON
- Optional MQTT sensors (current place, distance today)

**Location**
- One sensor with everyone's `Home` / `City, State` / zone name, and a count of who is home. **You choose its name** in the Configuration tab (or on the Location page) and Home Assistant follows when you change it
- Switches: tap `input_boolean` / `switch` entities to flip them
- Sensors to Device Trackers: turn any sensor into a real `device_tracker`
- Dashboard card: generates a Mushroom card (with Bubble separator) to paste into a dashboard

**Alerts**
- Per-place arrival notifications with an AI-written message, dwell time, days, time windows and cooldown
- Preview or send a test from the UI, and an Activity log

Requirements: an MQTT broker (Mosquitto add-on or external) for the location sensor's unique ID, an `ai_task` entity and a `notify.*` service for alerts. Open the **Documentation** tab for details.

Install: this add-on ships as a prebuilt image from the GitHub package `ghcr.io/jonathangibson98/{arch}-addon-location_hub`, so it installs fast on a Pi. Supports `aarch64` and `amd64`.
