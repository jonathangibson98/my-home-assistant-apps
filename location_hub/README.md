# Location Hub

Everyone's location sensor for Home Assistant, with, clickable switches, device trackers, a dashboard card generator and AI arrival alerts. One add-on, one sidebar entry.

**Location**
- One sensor with everyone's `Home` / `City, State` / zone name (or the place name once someone has stayed put for a set time), and a count of who is home. **You choose its name and entity ID** in the Configuration tab (or on the Location page) and Home Assistant follows when you change it
- Switches: tap `input_boolean` / `switch` entities to flip them
- Sensors to Device Trackers: turn any sensor into a real `device_tracker`
- Dashboard card: generates a Mushroom card (with Bubble separator) to paste into a dashboard

**Alerts**
- Per-place arrival notifications with an AI-written message, dwell time, days, time windows and cooldown
- Preview or send a test from the UI, and an Activity log

Requirements: an MQTT broker (Mosquitto add-on or external) for the location sensor's unique ID, an `ai_task` entity and a `notify.*` service for alerts. Open the **Documentation** tab for details.

Install: this add-on ships as a prebuilt image from the GitHub package `ghcr.io/jonathangibson98/{arch}-addon-location_hub`, so it installs fast on a Pi. Supports `aarch64` and `amd64`.
