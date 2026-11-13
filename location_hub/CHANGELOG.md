# Changelog

## 3.3.1

- Fix: background watchers (backstop, idle watch, restart after restore) are now kept referenced so Python cannot garbage-collect them mid-run.
- Health check uses the exec form, which the Dockerfile linter requires.
- Added a logo and fixed a typo in the README.

## 3.3.0

- **Backup & restore.** New Backup section (home page tile, or the Backup button at the top of the Location Hub
  page). Save everything the add-on keeps (devices, sensor trackers, dashboard card, sensor settings, alert
  places and people) plus the add-on options to a file in `/share/location_hub_backups`, which survives
  uninstalling the add-on. Restore from a saved backup or an uploaded file; a safety copy of your current data
  is saved first. The MQTT password is never written to a backup, and a restore keeps the one you have now.
- New options `backup_path` and `backup_keep` in the Configuration tab.

## 3.1.0

- **Idle place lookup.** When someone has stayed at one spot for the configured time, their entry on the
  location sensor now shows what is at their GPS coordinates (a business name, else a street address)
  instead of only `City, State`. It goes back to the city as soon as they move away.
- New options `idle_minutes` (default 10, `0` turns it off) and `idle_radius_m` (default 100) in the
  Configuration tab.
- Named zones and Home are unchanged: the lookup only replaces the `City, State` result.

## 3.0.0

- **Removed the map.** Live map, history, timeline, places, map settings, import/export/backfill, the read-only
  map and ingest API on port 8100, and the map's MQTT sensors are gone. The Location and Alerts pages are unchanged.
- The home page no longer has a Map group or the "who is where" strip, and the Hub pages have no Map button.
- Port 8100 and the `/homeassistant` config mount are no longer requested.
- Old map files (`/data/tracker.db`, the map's `settings.json`) are left in `/data` unused; you can delete them.
- The leftover MQTT entities the map created ("place", "distance today") stop updating; delete them in
  Home Assistant if they show up as unavailable.

## 2.4.3

- **Entity ID rename no longer fails silently.** *Location > Devices* now checks Home Assistant itself and shows
  either "Home Assistant is using sensor.x" in green or the exact reason it was refused in red.
- Saving the page now always asks Home Assistant to apply the entity ID, even when the add-on thought it already
  had it. (This was why it could look changed on the page while Home Assistant still had the old one.)
- Big entity lists no longer trip a message size limit.

## 2.4.2

- **The entity ID now follows the sensor name.** Before, it was stuck on whatever it was when first created.
  Set `sensor_name` (or rename on the Location page) and the add-on renames the entity ID in Home Assistant
  (`Household Locations` becomes `sensor.household_locations`). Existing installs get this on the first start
  after updating. Home Assistant does not update dashboards or automations that use the old ID.
- New **Entity ID** box on *Location > Devices* to pick your own ID. It is kept, not changed back.
- New option `sync_entity_id` (on by default). Turn it off to keep the entity ID you have.
- If you change the entity ID in Home Assistant itself, the add-on notices and follows it.
- If the new ID is taken by an old unavailable entity, the log says so and the rename is retried every 15 minutes.

## 2.4.1

- **Fixed person pictures showing only the forehead.** The old "keep the top" crop pinned the photo to
  the very top, which cut off faces in tall or low-framed photos. The automatic position is now a bit
  above center, where faces usually are.
- **New per-person picture position slider** (*Settings > Tracked devices > Appearance*, for people using
  a picture). Slide until your face is centered in the circle, with a live preview. **Auto** puts it back.
  It applies on the map, the chips and the settings list.
- *Settings > Display > Pictures in the circles* still has Center crop and Show the whole picture.

## 2.4.0

- **Prebuilt image.** `config.yaml` now has an `image:` line pointing at your GitHub package
  (`ghcr.io/jonathangibson98/{arch}-addon-location_hub`), so Home Assistant downloads the finished
  image instead of building it on the Pi. The repo's action builds it on every push to `main` with a new version, no tags needed (see the repo README).
- **You pick the sensor name in the Configuration tab.** `sensor_name` is now a plain name such as
  `Household Locations`. Change it, restart the add-on, and the sensor is renamed in Home Assistant.
  The entity ID and unique ID stay the same, so dashboards and automations keep working. Renaming on
  the Location page still works; whichever you changed last wins. The first start after updating keeps
  the name you already have.
- The version shown in the app and log now comes from `config.yaml`, so it can no longer fall out of date.
- Removed the leftover top-level `main.py` (an old stand-alone Location Hub entry point that was never used).
- Branding cleanup: the MQTT device is now called **Location Hub** (was "Mini Tracker") and GPX exports say
  Location Hub. Internal MQTT IDs are unchanged, so no sensors are duplicated.
- README and Documentation tab brought up to date.

## 2.0.0

- Combined **Mini Tracker** (1.1.1) and **Location Hub** (1.0.0) into one add-on. Every feature from both is kept.
- One process, one ingress port, one sidebar entry. New **home page** with a tile for every section (map tabs, Location pages, Alerts pages); click one to open it. The map is at `/map`, with a **Home** tab to return.
- The Hub's API moved to `/api/hub/*` and its files to `/data/hub`, so nothing clashes with the map's `/api/settings` and `/data/settings.json`.
- An existing Location Hub 1.x install is migrated automatically on first start (files moved to `/data/hub`, same sensor and trackers).
- Options are the Location Hub's (sensor name, unique ID, log level, MQTT broker). Log level is upper case (`INFO`).
- The read-only map and ingest API on port 8100 are unchanged and do not expose any Hub page.

## 1.1.1 - 2026-10-30

- Fixed pictures being cropped to the middle of the photo, which cut the top off heads in portrait
  photos. Pictures now keep the top by default. New setting *Display > Pictures in the circles*:
  keep the top, center crop, or show the whole picture.
- Coordinate links are readable in dark mode.
- Accuracy is hidden when Home Assistant reports 0.

## 1.1.0 - 2026-10-30

- People and device trackers now automatically use the **picture Home Assistant has for them**
  (person photo), or else the **icon Home Assistant has for them** (for example `mdi:account-heart`).
  Zones show their Home Assistant icon too. Changes in Home Assistant show up on the map by themselves.
- Every icon set you have is usable: all ~7,400 **MDI** icons (`mdi:` and the old `hass:`, bundled, works
  offline), your `custom_icons` folder as **`local:`** (and `custom:`), and any folder you added with
  **Auto Custom Icons** (found automatically, used as `<your prefix>:name`).
- New **icon picker** with search across all sets, in Settings (people) and in the place editor.
- Icons that cannot be loaded fall back to initials instead of a broken image.
- Your own choice in Mini Tracker still wins; leave the icon blank to follow Home Assistant.

## 1.0.0 - 2026-10-29

First release.

- Live map of your Home Assistant people and device trackers, styled like the HA map (circle
  avatars, accuracy circles, zones), with dark mode after sunset.
- History stored in SQLite on the Pi: trails, optional points, heatmap, and playback scrubber.
- Day timeline: automatic stop detection, trips with distance/time/average speed, "save as place".
- Places: your own named places plus Home Assistant zones, with time-at-place stats.
- Your own pictures and `custom:` SVG icons for people and places.
- Import history (Google Takeout, GPX, GeoJSON, OwnTracks, CSV, generic JSON) into any device.
- Backfill from Home Assistant's own recorder history.
- Export to GPX / CSV / JSON. Retention and delete tools.
- Separate read-only map URL for dashboards (`?dev=`, `?trail=`, `?theme=`, `?chips=`, `?follow=`).
- Ingest API for OwnTracks (HTTP), Overland, and plain JSON.
- Optional MQTT discovery sensors (place, distance today) through the Mosquitto app.
- Miles by default (kilometers optional).
