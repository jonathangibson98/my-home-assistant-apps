# Location Hub

Location Hub is the **Location** and **Alerts** pages for Home Assistant: who is home, switches, device trackers, a dashboard card and AI arrival alerts. One sidebar entry, one process. The Configuration tab holds the sensor name, log level and MQTT options (see *Configuration tab* below).

## Quick start

1. Install and **Start** the app.
2. Turn on **Show in sidebar**. A **Location Hub** entry appears in your sidebar and opens the home page.
3. Open **Location > Devices**, add one row per person (label and entity) and save.
4. Optional: set up **Alerts** (needs an `ai_task` entity and a `notify.*` service).

## Location and Alerts pages

The add-on opens on a **home page** with a tile for every section: the Location pages (Switches, Devices, Sensor trackers, Dashboard card) and the Alerts pages (Arrival places, People & sensors, Notifications, Activity). Click a tile to open that part. On the Location and Alerts pages use the **Home** button at the top to return. **Save changes** at the bottom of a Hub page saves everything you edited there. Switches apply instantly and need no save.

### Location

- **Switches**: live on/off for `input_boolean.*` / `switch.*` entities. They appear when a Dashboard card person has such a tap entity, or a Sensor tracker has "Show as switch" on.
- **Devices**: the sensor name, plus one row per person (label, entity, optional home-state override). The sensor state is the number of people home; each person is an attribute (`jon: Home`, `mj: Greenville, South Carolina`). Home is decided by `zone.home` for entities with GPS, or the entity's own state without GPS. Away cities come from OpenStreetMap Nominatim. After a person has stayed at one spot for `idle_minutes`, their entry becomes what is at those coordinates (for example `Starbucks` or `12 Oak Street`) until they move; named zones and Home are never replaced.
- **Sensor trackers**: each row becomes a `device_tracker`. A matching home state means Home at your house coordinates, anything else is Away, unavailable/unknown is ignored. Deleting a row deletes the tracker.
- **Dashboard card**: group, tap entity and picture per person, plus titles, columns and the separator. Save, then copy the YAML (needs Mushroom and Bubble Card from HACS). New people appear here after you save them on Devices.

### Alerts

- **Places**: zone, who triggers it, any/all mode, wait time, days, time window, title, extra details, custom style. Preview or Send test per place.
- **People & sensors**: the people alerts track, with notes for the message writer.
- **Notifications**: master switch, AI task entity, notify service, limits, global style, fallback text, household context sensor. The **Locations sensor** field is the "Our Locations" context for the AI. Leave it blank to use this add-on's own location sensor.
- **Activity**: the last 60 sent, skipped and previewed alerts.

Requirements for these pages: an MQTT broker (Mosquitto add-on or external) for the location sensor's unique ID (without one it falls back to a plain sensor with no unique ID), an `ai_task` entity and a `notify.*` service for alerts.

### Configuration tab

| Option | What it does |
| --- | --- |
| `sensor_name` | The name of the location sensor in Home Assistant, for example `Household Locations`. Change it and restart the add-on to rename the sensor (see *Naming the location sensor* below). |
| `sync_entity_id` | On by default. When the name changes, the entity ID is renamed to match. Turn off to keep your current entity ID. |
| `unique_id` | Optional. Paste the Unique ID from an old Location Tracker / Location Hub to keep the same sensor. First run only. |
| `idle_minutes` | Default 10. Once a person has stayed at one spot this many minutes, their entry on the location sensor shows what is there (a business name, else a street address) instead of `City, State`. `0` turns it off. |
| `idle_radius_m` | Default 100. How far (in meters) a phone can drift and still count as staying at one spot. |
| `backup_path` | Default `/share/location_hub_backups`. Where the Backup page saves backups. Must be inside `/share`. |
| `backup_keep` | Default 20. How many saved backups to keep; the oldest are deleted when you save a new one. |
| `log_level`, `log_location_updates` | Logging. |
| `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password` | For the location sensor and device trackers. Leave blank to use the Mosquitto add-on. |

Option changes need a restart.

### Naming the location sensor

Type the name you want in the `sensor_name` option, for example `Household Locations`, and restart the add-on. Home Assistant shows that name right away.

- The **entity ID** follows the name by default: `Household Locations` becomes `sensor.household_locations`. The add-on renames it in Home Assistant's entity registry for you (needs MQTT). The sensor keeps its permanent unique ID, so renaming never makes a duplicate. **Home Assistant does not update dashboards, cards or automations that use the old entity ID**, so change those yourself. Turn this off with the `sync_entity_id` option to keep the entity ID you have.
- If the rename says the ID is already used, an old unavailable entity is holding it. Delete that one in *Settings > Devices & services > Entities*, then restart the add-on.
- You can also rename it on the **Location > Devices** page without a restart. Whichever you changed last wins: if you rename on the page and later change the option, the option wins; restarting without touching the option keeps the page's name.
- Old-style values such as `sensor.location_tracker` still work and are shown as `Location Tracker`.
- Want an entity ID that is different from the name? On **Location > Devices**, type it in the **Entity ID** box (it must look like `sensor.something`) and save. Your choice is kept; it is not changed back later. Changing it in Home Assistant itself (the sensor's gear) also works, and the add-on picks it up.

### Prebuilt image

`config.yaml` has `image: "ghcr.io/jonathangibson98/{arch}-addon-location_hub"`. Home Assistant replaces `{arch}` with `aarch64` or `amd64` and downloads that image, tagged with the add-on's version, instead of building on your Pi. The repo's GitHub Action builds and publishes it whenever you push to `main` with a new `version` (no tags or releases needed). The package must be **public** or Home Assistant cannot pull it. If an install says the image was not found, the build has not finished yet (check the Actions tab) or the version in `config.yaml` was never pushed.

### Data stored

The pages keep `devices.json`, `trackers.json`, `settings.json`, `card.json` and `config.json` in `/data/hub`, which is included in add-on backups.

### Moving over from the separate add-ons

- **From Location Hub 1.x or 2.x** (slug `location_hub`): install this version over it. Your settings are kept. The map and its history are gone; `tracker.db` and the map's old `settings.json` stay in `/data` unused and can be ignored.
- **From Location Tracker / Arrival Alerts**: add-ons cannot read each other's data, so re-enter settings once. To keep the old location sensor, copy the **Unique ID** from the old Location Tracker UI into the `unique_id` option before the first start.
- Stop the old add-ons first: they use the same ingress port and MQTT topics.
- If a sensor or device tracker comes up with a `_2` suffix, delete the old unavailable entity in Settings, Entities, then restart.

## Backups

Two ways, and they work together:

- **The Backup page** (home page tile, or the **Backup** button at the top of the page). **Save backup now** writes one JSON file with your devices, sensor trackers, dashboard card, sensor settings, alert places and people, and the add-on options. Files go to `backup_path` (default `/share/location_hub_backups`), which is **kept when you uninstall the add-on**. The newest `backup_keep` (default 20) are kept. **Download a copy** saves the same file to your phone or computer.
- **Restore** picks a saved backup, or a file you upload. Before anything changes, a safety copy of your current data is saved (shown in the same list, never deleted automatically). Then the files are replaced, the add-on options are restored if you leave that ticked, and the add-on restarts. Your MQTT password is never put in a backup, and a restore keeps the one you have now.
- **Home Assistant's own backups** also include the add-on's `/data`, and are the way to carry the add-on's options across an uninstall if you did not save a backup first.

To move to a fresh install: save a backup, uninstall, reinstall, open the Backup page and restore it.

## Troubleshooting

- **Location sensor unavailable**: check MQTT. The Location page shows `Mode: MQTT` or `REST (no unique ID)`.
- **Someone shows `unknown`**: wrong entity ID. Check Developer Tools, States.
- **Alerts never send**: check Alerts > Activity for "skipped" reasons (cooldown, time window, paused) and that the AI entity and notify service are set on the Notifications page.
- **Log shows MQTT errors**: install and start the Mosquitto broker app, or enter your broker details manually.

Set the log level to `DEBUG` in the app's Configuration tab for more detail.

## What it does not do

- It does not talk to Apple, Google or any cloud service for locations. It only reads Home Assistant. Away city names and idle place names come from OpenStreetMap Nominatim.
- It does not record location history or draw a map.
