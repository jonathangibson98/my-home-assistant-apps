# Changelog

## 3.8.0 - 2026-11-25

- **The dashboard card is created and updated for you.** On the Dashboard card tab, turn on **Keep a dashboard card up to date** and the add-on puts the card into Home Assistant itself, so there is no more copying YAML. It rechecks when you save, when you change devices, and every couple of minutes, and only writes when something actually changed.
  - **Its own dashboard** (default): creates a **Location Hub** dashboard (optionally in the sidebar) with a People view.
  - **Add to one I have**: adds a single **People** view to a dashboard you already use. Everything else in that dashboard is left alone. A dashboard that is still automatic must be taken control of first (the page says so), because saving would otherwise replace it.
  - The page shows when it last checked, whether it changed anything, a link to open it, and a warning when Mushroom or Bubble Card isn't installed as a dashboard resource.
  - **Update now** forces a refresh. The old **Card YAML** is still there, folded away, if you would rather paste it.
- The add-on only ever rewrites its own **People** view (path `location-hub`). Don't add your own cards to that view.

## 3.7.0 - 2026-11-23

- **Dashboard card tab, simpler and with a live preview.**
  - **Preview** at the top shows the actual tiles (picture, name, where they are now, home dot), grouped and in your column count. It updates as you change anything, before you save.
  - **Pick pictures with a tap.** Tap a person's picture, then choose **Automatic**, a picture from Home Assistant people, one of your images in the `www` folder, **Upload from this device** (a photo from your phone), or paste a link. No more typing paths.
  - **Group buttons** (Household / Friends / Hidden) instead of a drop-down. The tap entity is tucked under each person, and titles, columns and the separator are under one fold-out.
  - The **Card YAML** now refreshes live too, not only after saving. Everything the tab did before is still there.
- **New access:** the add-on now sees your Home Assistant config folder, only to list pictures in `www` and save uploads to `www/location_hub/` (they show up as `/local/location_hub/...`). If you never had a `www` folder, restart Home Assistant once after your first upload so `/local` works.
- Uploads accept JPG, PNG, WebP and GIF up to 8 MB.

## 3.6.2 - 2026-11-17

- **Easier to read over wallpapers.** The page checks how bright the wallpaper is and tints behind the text just enough to keep it readable: bright wallpapers get more, dark ones barely any.

## 3.6.1 - 2026-11-17

- Uses the shared **add-on wallpaper** you pick in Photo Hub (new *Add-on wallpaper* tab). This add-on's own Wallpaper option still wins when set.

## 3.6.0 - 2026-11-16

- **Pick the web UI wallpaper.** New **Wallpaper** option on the Configuration tab. Leave it empty to use your Home Assistant theme's wallpaper, enter `none` for no wallpaper, or point it at your own image: drop it in `/config/www` and enter the file name (e.g. `wallpaper.jpg`), `/local/wallpaper.jpg`, or a full `https://` link.

## 3.5.0 - 2026-11-16

- **Follows your Home Assistant theme.** The web UI now uses the colors of whatever theme Home Assistant is showing, light or dark, and changes live when you switch. Themes with a dashboard wallpaper and frosted-glass cards (like Apple / Liquid Glass themes) carry over too: wallpaper behind, see-through blurred cards, matching corners. Opened outside Home Assistant it keeps its own look.

## 3.4.1

- Removed personal names, places and home-specific entity IDs from the defaults, examples and docs, so new installs start clean.

## 3.4.0

- **New Arrivals section** (home page tiles, or the Arrivals button at the top of the Location Hub page). It does
  what the AppDaemon `PresenceSensors` app did (`sensor.arrived_home`), inside the add-on, and for **any zone**,
  not only home.
- Every zone gets a sensor, `sensor.arrived_<zone>` (Home is `sensor.arrived_home`). The state is who arrived:
  `alex_home`, `alex_sam_work`, or a **group name** you set for an exact set of people. People who arrive at the
  same place within the **group window** count as one group.
- After the **clear time** the sensor returns to `no one arriving`. With nobody at the place it shows `nobody home`
  (Home) or `nobody here` (any other zone). Each sensor has a `<person>_<zone>` true/false attribute per person.
- `sensor.latest_arrival` shows the newest arrival at any zone, and each arrival fires a `location_hub_arrival`
  event (place, zone, people, key) for automations.
- People come from **Location > Devices**, so there is nothing to enter twice. A **Live** tab shows every sensor,
  has a Test arrival button, and keeps an activity list.
- Arrival settings are included in Backup & restore.

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
