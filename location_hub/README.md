# Location Hub

Everyone's location, clickable switches, device trackers, a dashboard card generator and AI arrival alerts, all in one add-on and one web UI.

**Location** (from Location Tracker)
- One sensor with everyone's `Home` / `City, State` / zone name, and a count of who is home
- Switches: tap `input_boolean` / `switch` entities to flip them
- Sensors to Device Trackers: turn any sensor into a real `device_tracker`
- Dashboard card: generates a Mushroom card (with Bubble separator) to paste into a dashboard

**Alerts** (from Arrival Alerts)
- Per-place arrival notifications with an AI-written message, dwell time, days, time windows and cooldown
- Preview or send a test from the UI, and an Activity log

Requirements: an MQTT broker (Mosquitto add-on or external) for the location sensor's unique ID, an `ai_task` entity and a `notify.*` service for alerts. See DOCS.md.
