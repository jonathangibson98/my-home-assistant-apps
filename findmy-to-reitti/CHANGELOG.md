# Changelog

## 1.0.0

First release. Built from the "Who's Here" add-on.

- Forwards Find My (Apple iCloud integration) device locations to Reitti
- Web UI in the HA sidebar: Reitti address, default token, check interval
- Per-device name, tracked entity, device ID, on/off switch, and token override
- "Send now" button and a live status line for each device
- Only sends when a device's location actually changes
- Settings saved in the add-on's `/data` folder, so they survive restarts and updates
- Removed from Who's Here: MQTT, places, and the dashboard card generator
