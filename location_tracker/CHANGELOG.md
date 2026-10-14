# Changelog

## Latest

### Added
- **Sensors to Device Trackers** section in the web UI. Pick a sensor, and it becomes a real `device_tracker` entity.
  - State matches your home state: Home, at your house coordinates (from `zone.home`).
  - Any other state: Away.
  - Unavailable or unknown states are ignored, so restarts don't flip anyone to away.
  - Several home states can be listed, separated by commas.
  - Deleting a row removes the device tracker from Home Assistant.
- Page now scrolls sideways on small screens and has a mobile viewport tag.

### Fixed
- The Entity ID line in the web UI no longer shows the wrong ID after you rename the sensor. The entity ID is now fixed when the sensor is created.
- A double quote typed into a label or entity ID can no longer break the device table.

## Earlier

### Added
- Sensor name editable in the web UI, with a permanent unique ID so renaming never creates a duplicate.
- Publishes through MQTT discovery, so the sensor has a real unique ID and can be edited in the UI.
- External MQTT broker support (`mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password`).
- Automatic REST fallback if MQTT isn't available.
- Device list editable in the web UI, with a per-person home state override.
- Log level and update logging options.

### Changed
- Reconnects on its own after Home Assistant restarts, and republishes the sensor when HA finishes starting.

### Initial release
- Tracks everyone's location as "Home", "City, State", or a named zone using Nominatim.
- "Home" is only counted when GPS is inside your own home zone.
