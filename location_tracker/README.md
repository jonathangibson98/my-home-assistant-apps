# Location Tracker

Shows everyone's location as a single Home Assistant sensor. Anyone who's away gets a readable **City, State** instead of raw coordinates, and a count of how many people are home.

## What it does

- Tracks any `device_tracker.*` or `sensor.*` entity you give it
- Looks up **City, State** for anyone who's away (OpenStreetMap Nominatim, no API key)
- Checks GPS coordinates against **your** `zone.home`, so someone at another house that also reports "home" doesn't count as home at yours
- Entities with no GPS (simple presence sensors) are trusted at their word
- Named HA zones (like "Work") are shown as-is
- **Custom places:** add your own spots (name, coordinates, radius) in the Web UI and anyone inside one shows that name instead of City, State
- **Dashboard card generator:** builds a Mushroom card for everyone from the Web UI, ready to copy into your dashboard
- Updates instantly when any tracked entity changes, plus a 30-minute safety refresh
- Creates a real sensor with a **unique ID** (via MQTT discovery), so you can rename it, change its icon, and assign it an area from the HA UI

## The sensor

- **State:** number of people currently home
- **Attributes:** one per person, using the lowercase label you set (for example `jon: Home`, `mj: Greenville, South Carolina`)

Example template:

```yaml
{{ state_attr('sensor.location_tracker', 'jon') }}
```

## Requirements

- Home Assistant OS or Supervised (add-ons)
- **Mosquitto broker** add-on installed and running
- **MQTT integration** set up in Home Assistant

No MQTT? The add-on still works. It falls back to a plain sensor with no unique ID, and the Web UI will say so.

## Setup

1. Install and start the add-on.
2. Click **Open Web UI**.
3. Type a **Sensor name** (this becomes the entity ID the first time, for example "Everybody's Locations" becomes `sensor.everybodys_locations`).
4. Click **+ Add Device** for each person:
   - **Label:** a name like `Jon` (saved lowercase, spaces become underscores)
   - **Entity ID:** for example `device_tracker.jon_phone` or `sensor.mj_presence`
   - **Home State Override:** only if the entity reports something other than `home` when someone's there (like `on` or `present`). Not case sensitive.
5. (Optional) Under **Places**, click **+ Add Place** for spots you want named. Enter a name, coordinates, and a radius in meters (100 is a good start). Copy coordinates from your maps app and paste the whole `34.5123, -82.4567` into Latitude, leaving Longitude blank. Standing at the spot? Tap **Add Place at My Location**.
6. Click **Save Changes**.

## Places

- A place only applies to entities that report GPS coordinates.
- If a tracker is already inside a named HA zone, that zone name wins. Places replace the City, State lookup.
- If places overlap, the one whose center is closest wins.
- Your home is still handled by `zone.home`, not by places.

## Tips

- Not sure what your entity says when someone's home? Check **Developer Tools → States** in Home Assistant.
- If a person shows `unknown`, the entity ID is wrong or doesn't exist.
- Renaming the sensor later changes its display name, not its entity ID. To change the entity ID, use the entity settings in HA.
- The unique ID is created once and stored in the add-on's data. Uninstalling the add-on resets it.

## Add-on options

| Option | Description |
| --- | --- |
| `sensor_name` | Default name used the first time only. After that, the Web UI name is used. |
| `log_level` | `DEBUG`, `INFO`, `WARNING`, or `ERROR` |
| `log_location_updates` | Log every update at INFO level (turn off for quieter logs) |

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Web UI says `Mode: REST (no unique ID)` | MQTT isn't connected. Check that Mosquitto is running and the MQTT integration is set up, then restart the add-on. |
| Sensor shows up as `sensor.xxx_2` | An old sensor with the same name existed. Restart Home Assistant, or delete the old one. |
| Dashboard shows blank for a person | Attribute names are lowercase now. Use `jon`, not `Jon`. |
| Person never shows as home | Their entity doesn't say `home`. Set the **Home State Override** to the exact state it shows. |
| Build fails on the pip line | Check the build log and make sure the Dockerfile installs `paho-mqtt>=2,<3`. |

## Notes

City/State lookups use the free OpenStreetMap Nominatim service, and results are cached by location to stay well inside their usage limits.
