# Changelog

## Latest v0.10.0

### Added
- **Switches** section at the top of the web UI. Click a switch to toggle that entity in Home Assistant. It shows live state and refreshes every few seconds. No save needed.
  - Includes any Dashboard Card person whose tap entity is an `input_boolean.*` or `switch.*`.
  - Includes any Sensors to Device Trackers row with the new **Toggle** checkbox ticked (toggles that row's source sensor).
  - Only entities in those lists can be toggled, and only `input_boolean` and `switch` domains.

## Earlier v0.9.1

### Fixed
- The `away` state (not_home with no GPS) now shows as `Away`, capitalized, to match `Home`.

## Earlier v0.9.0

### Added
- **Dashboard Card** section in the web UI. It builds a Mushroom card (with the Bubble separator on top) from your people list, ready to copy and paste into a dashboard.
  - Per person: group (Household, Friends, or Hidden), tap entity, and an optional picture.
  - `input_boolean.*` tap entities toggle on tap. Anything else does nothing on tap.
  - Picture is automatic: `person.*` uses that person's profile picture, anything else uses `/local/person/<name>.png`.
  - Group titles, column count, and the separator are editable.
  - **Copy Card YAML** button. The YAML refreshes every time you save.
  - Your first load is pre-filled to match your current card.

## Earlier v0.8.1

### Added
- **Sensors to Device Trackers** section in the web UI. Pick a sensor, and it becomes a real `device_tracker` entity.
  - State matches your home state: Home, at your house coordinates (from `zone.home`).
  - Any other state: Away.
  - Unavailable or unknown states are ignored, so restarts don't flip anyone to away.
  - Several home states can be listed, separated by commas.
  - Deleting a row removes the device tracker from Home Assistant.
- Page now scrolls sideways on small screens and has a mobile viewport tag.

### Fixed
- Device trackers that go Away now send blank coordinates and publish them before the state, so nothing can linger on the map at your house.
- The Entity ID line in the web UI no longer shows the wrong ID after you rename the sensor. The entity ID is now fixed when the sensor is created.
- A double quote typed into a label or entity ID can no longer break the device table.

## Earlier v0.8.0

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
