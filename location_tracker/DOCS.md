# Location Tracker: Documentation

Tracks where everyone is and publishes it as one Home Assistant sensor. It can also turn plain sensors into real `device_tracker` entities.

## Requirements

- An MQTT broker. Either the Mosquitto broker app on this machine, or an external broker you enter in the Configuration tab.
- The MQTT integration set up in Home Assistant.
- A `zone.home` zone (Home Assistant creates this by default).

If MQTT can't be reached, the app falls back to the REST API. Everything still works, but the entities have no unique ID, so you can't edit them in the UI. The web UI shows which mode you're in.

## Web UI

Open the app from the sidebar. There are four sections, and **Save Changes** at the bottom saves all of them.

### Sensor

The display name of the main location sensor. Renaming changes the display name only. The entity ID is fixed when the sensor is first created. To change it, use Settings, Entities, then the sensor.

### Location Tracker Devices

One row per person.

| Column | What it does |
|---|---|
| Label / Person | The name used as the attribute key. Lowercased, spaces become underscores (`MJ Phone` becomes `mj_phone`). |
| Entity ID | The tracker or sensor to watch, such as `device_tracker.jon_phone`. |
| Home State Override | Optional. The exact state that means "home" for this person. Not case sensitive. |

### Sensors to Device Trackers

One row per sensor you want converted into a `device_tracker`.

| Column | What it does |
|---|---|
| Name | Display name of the new device tracker. |
| Source sensor | The sensor to read, such as `sensor.mj_location`. |
| Home state | The state that means home. Leave blank for `home`. Separate several with commas (`home, house`). |
| Device tracker ID | Read only. Shown after the first save. |

How it converts:

- **Matches the home state:** the tracker state is `home`, and its latitude and longitude are copied from `zone.home`, so it sits on your house.
- **Anything else:** the tracker state is `not_home`, with no coordinates.
- **Unavailable or unknown:** ignored. The tracker keeps its last state, so a restart doesn't flip anyone to away.
- Deleting a row and saving removes that device tracker from Home Assistant.

### Dashboard Card

Builds the Mushroom card for your dashboard from the people in the list above. New people show up here after you save.

| Column | What it does |
|---|---|
| Person | The label from the devices list. Read only. |
| Group | Household, Friends, or Hidden (left out of the card). |
| Tap entity | The entity behind the tile. `input_boolean.*` toggles on tap. Anything else does nothing. Blank means no entity. |
| Picture | Optional. Blank is automatic: `person.*` uses that person's profile picture, anything else uses `/local/person/<name>.png`. |

Above the table you can change the two group titles, the number of columns, and whether the Bubble Card separator is included.

To use it: click **Save Changes**, click **Copy Card YAML**, then in your dashboard choose Edit, Add card, Manual, and paste. The card needs the Mushroom and Bubble Card integrations from HACS.

## The sensor

**State:** the number of people currently home.

**Attributes:** one per person, keyed by their label. Each value is one of:

| Value | Meaning |
|---|---|
| `Home` | At your home (see rules below). |
| `City, State` | Away, with GPS. Looked up through OpenStreetMap Nominatim. |
| A zone name | In one of your other named zones, shown as is. |
| `away` | Reports not_home with no GPS. |
| `unknown` | The entity wasn't found. |

### How "Home" is decided

1. If a Home State Override is set and the entity's state matches it, the person is Home.
2. If the entity has GPS coordinates and no override is set, they are Home only when inside your `zone.home` radius. This stops "home" at someone else's house from counting.
3. If the entity has no coordinates, its own `home` state is trusted (when no override is set).

## When it updates

- Instantly when a watched entity changes state.
- When Home Assistant finishes starting.
- Every 30 minutes as a backup.
- When you save in the web UI.

## Configuration tab

| Option | What it does |
|---|---|
| `sensor_name` | Starting name for the sensor, used only the first time. |
| `log_level` | `DEBUG`, `INFO`, `WARNING`, or `ERROR`. |
| `log_location_updates` | Turn off to stop logging every update. |
| `mqtt_host` | Leave blank to use the Mosquitto app. Fill in to use an external broker. |
| `mqtt_port` | External broker port. Defaults to 1883. |
| `mqtt_username` / `mqtt_password` | External broker login. |

Changes to these options need an app restart.

## Where your data is stored

Saved inside the app's private storage and included in Home Assistant backups of the app:

- `devices.json`: the people list
- `trackers.json`: the sensors to convert
- `settings.json`: the sensor name and its permanent IDs
- `card.json`: the dashboard card settings

## Troubleshooting

- **Sensor shows unavailable:** the app is stopped, or lost its MQTT connection. Check the Log tab.
- **Log says "MQTT not available":** the broker isn't reachable. Check that the Mosquitto app is running, or the external broker details.
- **Someone shows `unknown`:** the entity ID is wrong. Check it in Developer Tools, States.
- **A device tracker didn't appear:** save in the web UI, wait a few seconds, then look in Settings, Entities.
- **Got a duplicate sensor ending in `_2`:** another app or AppDaemon script is using the same entity ID. Turn one off.
- **City shows `unknown location`:** Nominatim didn't answer in time. The next update tries again.

## Notes

- Nominatim asks for about one request per second at most. Results are cached by location, so this is rarely a problem.
- Renaming never creates a duplicate, because the unique ID never changes.
