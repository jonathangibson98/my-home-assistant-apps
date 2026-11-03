# Location Hub: Documentation

Open the add-on from the sidebar. The top switch picks **Location** or **Alerts**; the pills below pick the page. **Save changes** at the bottom saves everything you edited. Switches apply instantly and need no save.

## Location

- **Switches**: live on/off for `input_boolean.*` / `switch.*` entities. They appear when a Dashboard card person has such a tap entity, or a Sensor tracker has "Show as switch" on.
- **Devices**: the sensor name, plus one row per person (label, entity, optional home-state override). The sensor state is the number of people home; each person is an attribute (`jon: Home`, `mj: Greenville, South Carolina`). Home is decided by `zone.home` for entities with GPS, or the entity's own state without GPS. Away cities come from OpenStreetMap Nominatim.
- **Sensor trackers**: each row becomes a `device_tracker`. A matching home state means Home at your house coordinates, anything else is Away, unavailable/unknown is ignored. Deleting a row deletes the tracker.
- **Dashboard card**: group, tap entity and picture per person, plus titles, columns and the separator. Save, then copy the YAML (needs Mushroom and Bubble Card from HACS). New people appear here after you save them on Devices.

## Alerts

- **Places**: zone, who triggers it, any/all mode, wait time, days, time window, title, extra details, custom style. Preview or Send test per place.
- **People & sensors**: the people alerts track, with notes for the message writer.
- **Notifications**: master switch, AI task entity, notify service, limits, global style, fallback text, household context sensor.
  The **Locations sensor** field is the "Our Locations" context for the AI. Leave it blank to use this add-on's own location sensor.
- **Activity**: the last 60 sent, skipped and previewed alerts.

## Configuration tab

| Option | What it does |
| --- | --- |
| `sensor_name` | Starting name for the location sensor (first run only). |
| `unique_id` | Optional. Paste the Unique ID from the old Location Tracker UI to keep the same sensor. First run only. |
| `log_level`, `log_location_updates` | Logging. |
| `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password` | Leave blank to use the Mosquitto add-on. |

Option changes need a restart.

## Moving over from the two old add-ons

Add-ons cannot read each other's data, so settings start fresh:

1. Open each old add-on and note your settings (devices, trackers, card, places, people, notification settings).
2. Optional, to keep the existing sensor: copy the **Unique ID** shown at the top of the old Location Tracker UI into this add-on's `unique_id` option before the first start.
3. Stop the old add-ons, start Location Hub, and re-enter your settings.
4. If a sensor or device tracker comes up with a `_2` suffix, delete the old unavailable entity in Settings, Entities, then restart Location Hub. Rename the new one if needed.

Both old add-ons used port 8099 and the same MQTT topics style, so do not run them alongside this one.

## Data stored (included in add-on backups)

`devices.json`, `trackers.json`, `settings.json`, `card.json` (location side) and `config.json` (alerts).

## Troubleshooting

- Location sensor unavailable: check MQTT. The UI shows `Mode: MQTT` or `REST (no unique ID)` on the Devices page.
- Someone shows `unknown`: wrong entity ID. Check Developer Tools, States.
- Alerts never send: check Activity for "skipped" reasons (cooldown, time window, paused) and that the AI entity and notify service are set on the Notifications page.
