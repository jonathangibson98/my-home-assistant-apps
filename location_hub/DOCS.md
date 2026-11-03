# Location Hub

Location Hub is two tools in one add-on: a **location history map** (the home page) and the **Location** and **Alerts** pages (who is home, switches, device trackers, a dashboard card and AI arrival alerts). One sidebar entry, one process.

The map is a lightweight location history map that lives inside Home Assistant. It records where your
people and devices have been, and shows it on a map with trails, playback, stops, places and a
heatmap. Everything is stored on your own Pi, and everything on the map is set up from the app's own
**Settings** tab. The Configuration tab holds the log level and the location sensor / MQTT options (see *Configuration tab* below).

## Quick start

1. Install and **Start** the app (see the repo README for how to add it).
2. Turn on **Show in sidebar**. A **Location Hub** entry appears in your sidebar.
3. Open it. On the first start, every Home Assistant **person** that has GPS is tracked
   automatically. Your devices show up on the map within seconds.
4. Open **Settings > Tracked devices** to add or remove people and device trackers, set names,
   colors and pictures.
5. Want history from before today? **Settings > Data > Backfill** pulls past locations from
   Home Assistant, and **Import** reads files such as Google Takeout.

## Where the locations come from

Mini Tracker listens to Home Assistant over the Supervisor connection the app already has, so
there is **no token to create** and nothing to configure. Any `person.*` or `device_tracker.*`
entity that has latitude and longitude can be tracked. That includes the Companion app,
iCloud-style integrations, and your own device trackers.

Points are filtered before they are stored:

| Setting | Default | What it does |
| --- | --- | --- |
| Record when moved at least | 15 m | Ignores jitter while you are standing still |
| Heartbeat while still | 10 min | Stores a point this often even without movement, so stops have real durations |
| Ignore fixes worse than | 200 m | Drops very inaccurate GPS fixes |
| Keep history for | forever | Set days to auto-delete old points |

## The tabs

**Live**: who is where right now, how fresh the data is, battery and accuracy.

**History**: pick devices and a range (today, yesterday, 3/7/30 days, or custom), then **Show
history**. Options:

- *Show points* draws every recorded point (tap one for its time).
- *Heatmap* shows where you spend time.
- *Playback* appears under the summary: press play or drag the slider to watch the trip unfold.
  The whole range plays in about a minute at 1x.

**Timeline**: a day at a glance. Stops are detected automatically (default: 10 minutes within
75 m). Each stop is matched to your places and Home Assistant zones. Trips between stops show
distance, time and average speed. Tap a trip to draw it on the map. Unknown stops have a
**Save as place** button.

**Places**: your own named places (tap **Add place**, tap the map, set the radius) plus your
Home Assistant zones. **Time at places** totals how long a device spent at each place over
7, 30 or 90 days.

**Settings**: devices, display, recording, data tools, and integrations.

## Location and Alerts pages

The map's tab bar ends with **Location ↗** and **Alerts ↗**. They open the Location Hub pages; the **Map** button at the top of those pages brings you back. **Save changes** at the bottom of a Hub page saves everything you edited there. Switches apply instantly and need no save.

### Location

- **Switches**: live on/off for `input_boolean.*` / `switch.*` entities. They appear when a Dashboard card person has such a tap entity, or a Sensor tracker has "Show as switch" on.
- **Devices**: the sensor name, plus one row per person (label, entity, optional home-state override). The sensor state is the number of people home; each person is an attribute (`jon: Home`, `mj: Greenville, South Carolina`). Home is decided by `zone.home` for entities with GPS, or the entity's own state without GPS. Away cities come from OpenStreetMap Nominatim.
- **Sensor trackers**: each row becomes a `device_tracker`. A matching home state means Home at your house coordinates, anything else is Away, unavailable/unknown is ignored. Deleting a row deletes the tracker. (These new trackers can also be tracked on the map from **Settings > Tracked devices**.)
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
| `sensor_name` | Starting name for the location sensor (first run only). |
| `unique_id` | Optional. Paste the Unique ID from an old Location Tracker / Location Hub to keep the same sensor. First run only. |
| `log_level`, `log_location_updates` | Logging. |
| `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password` | For the location sensor and device trackers. Leave blank to use the Mosquitto add-on. (The map's own MQTT sensors are set in the map's Settings.) |

Option changes need a restart.

### Data stored

The Hub pages keep `devices.json`, `trackers.json`, `settings.json`, `card.json` and `config.json` in `/data/hub`. The map keeps its own `settings.json` and `tracker.db` in `/data`. All of it is included in add-on backups.

### Moving over from the separate add-ons

- **From Location Hub 1.x** (slug `location_hub`): install this version over it. On first start its files are moved into `/data/hub` automatically and everything carries on, including the same sensor. The map starts empty: use **Settings > Data > Backfill** to pull history from Home Assistant.
- **From Location Tracker / Arrival Alerts or Mini Tracker**: add-ons cannot read each other's data, so re-enter settings once. To keep the old location sensor, copy the **Unique ID** from the old Location Tracker UI into the `unique_id` option before the first start. Mini Tracker history can be re-created with Backfill, or by importing a GPX/CSV export from the old one.
- Stop the old add-ons first: they use the same ingress port and MQTT topics.
- If a sensor or device tracker comes up with a `_2` suffix, delete the old unavailable entity in Settings, Entities, then restart.

## Icons and pictures

**By default Mini Tracker uses whatever Home Assistant uses**, so it looks right without setup:

| For | It shows |
| --- | --- |
| A person or device tracker | The picture Home Assistant has for it (for example a person's photo), otherwise its Home Assistant icon (for example `mdi:account-heart`), otherwise initials |
| A Home Assistant zone | The zone's icon (for example `mdi:home`) |
| A place you add here | The icon you pick, otherwise initials |

If you change a person's picture or an icon in Home Assistant, the map follows within a few seconds.
A person or zone with no picture or icon shows initials.

**To override it**, open *Settings > Tracked devices*, find the device, and use **Pick**, type an
icon, or **Upload picture**. Leave the field blank (or press **Use Home Assistant's (auto)** in the
picker) to go back to following Home Assistant.

### Icon sets you can use

| Prefix | What it is |
| --- | --- |
| `mdi:` and `hass:` | All Material Design Icons (about 7,400, built in, works offline). `hass:` is the old name for `mdi:` |
| `local:` and `custom:` | The SVG files in your icons folder, `/config/custom_icons` by default (change it under *Settings > Display*). Subfolders work: `local:rooms/kitchen`. This is the same folder the *Custom Icons* integration uses |
| `<your prefix>:` | Each folder you added with the **Auto Custom Icons** integration, found automatically. A folder `my_icons` with prefix `my_icons` gives `my_icons:garage` |
| an emoji | Type one into the icon field |
| a picture | *Upload picture* (cropped to a square, 128 px) |

The **Pick** button opens a search across every set at once, with your own icons listed first.

Good to know:

- MDI is bundled at version 7.4.47. If Home Assistant has a newer icon that is not in this version, that
  one falls back to initials until the app is updated.
- Icon sets that need their own files to work (for example Font Awesome Pro or the `phu:` Hue icons) are not
  available here, and fall back to initials.
- Pictures are cropped to fit the circle. By default the crop keeps the **top** of the photo so heads
  are not cut off. If a picture still looks wrong, change *Settings > Display > Pictures in the circles*
  to **Show the whole picture**.
- SVG files keep their own colors. An SVG that is plain black will look black on the white badge.
  `mdi:` icons are drawn white on the device's color.
- To find your Auto Custom Icons folders, the app reads Home Assistant's integration list
  (`/config/.storage/core.config_entries`, read-only) and picks out only the Auto Custom Icons entries.
  Nothing else in that file is used or stored.
- The app has read-only access to your config folder. Person pictures come from Home Assistant itself
  (or `/config/www` for `/local/...` pictures).

## Dark mode

*Settings > Display > Theme* offers **Dark after sunset** (uses your `sun.sun` entity, falling
back to 7 pm to 7 am), **Follow device**, **Always light** and **Always dark**. With
OpenStreetMap tiles the map is inverted at night; with CARTO tiles the map switches to CARTO's
native dark style. You can also paste any tile URL.

## Units

Miles and feet by default. Switch to kilometers in *Settings > Display*.

## Read-only map for your dashboard

The app also serves a second, **read-only** page on port **8100**. It has no settings button
and cannot change anything:

```
http://<your-home-assistant-ip>:8100/
```

Add it to a dashboard with an iframe card:

```yaml
type: iframe
url: http://homeassistant.local:8100/?trail=12&chips=0
aspect_ratio: 100%
```

URL options (combine with `&`):

| Option | Example | Meaning |
| --- | --- | --- |
| `dev` | `dev=person.jon,person.mj` | Only show these devices |
| `trail` | `trail=24` | Draw the last N hours as a trail |
| `theme` | `theme=dark` | `dark`, `light`, `auto` or `system` |
| `chips` | `chips=0` | Hide the people bar at the top |
| `follow` | `follow=person.jon` | Keep the map centered on one device |

**HTTPS note:** if you open Home Assistant over https (Nabu Casa, DuckDNS, a reverse proxy),
browsers block an `http://` iframe inside it. Put the 8100 port behind your reverse proxy with
https (for example a Nginx Proxy Manager host pointing at `<ip>:8100`) and use that https URL.

**Privacy note:** the read-only page has no password. Anyone on your network who can reach port
8100 can see the map and history. You can turn it off in *Settings > Read-only map*, or remove
the port number in the app's **Network** section.

## Importing history

*Settings > Data > Import history file*. Choose which device the points belong to (or give a
new device a name), then pick a file. Supported:

- **Google Takeout / Timeline**: `Records.json` from older exports, and `Timeline.json`
  exported from the Google Maps app on your phone.
- **GPX** tracks, **GeoJSON** (including Overland exports), **OwnTracks** `.rec` files,
  **CSV** with `lat`, `lon` and a time column, and any JSON list with lat/lon/time fields.

Large files are streamed, so a several-hundred-MB Takeout file will not run the Pi out of
memory, but it can take a few minutes. Leave **Thin out redundant points** on unless you want
every single point. Re-importing the same file is safe: duplicates are skipped.

## Backfill from Home Assistant

*Settings > Data > Backfill* copies past locations from Home Assistant's own database for your
tracked devices. Home Assistant only keeps about 10 days by default, so this mainly helps right
after installing.

## Exporting and deleting

*Settings > Data > Export* downloads a device's history as GPX, CSV or JSON. The same section
can delete points older than N days, or everything for one device.

## Other apps that send locations (ingest API)

Turn on *Settings > Read-only map, ingest & MQTT > Ingest API* (this needs the read-only map
enabled, since it uses port 8100). Copy the **endpoint** and **token** shown there.

| App | How to set it up |
| --- | --- |
| **OwnTracks** | Mode: HTTP. URL: `http://<ip>:8100/api/ingest?token=TOKEN` |
| **Overland** | Receiver endpoint: `http://<ip>:8100/api/ingest?token=TOKEN&device_id=my-phone` |
| **Anything else** | `curl -X POST "http://<ip>:8100/api/ingest?token=TOKEN" -H "Content-Type: application/json" -d '{"device":"my gps","lat":40.1,"lon":-75.2}'` |

Each new device name becomes an *external* device (`ext.<name>`) with its own color and
picture. Accepted fields: `lat`, `lon`, plus optional `timestamp` (seconds, milliseconds or
ISO text), `accuracy` and `battery`. To use these apps away from home you need the port
reachable from outside, for example through your reverse proxy. Use https and keep the token
secret. **New token** invalidates the old one.

## Publish to Home Assistant (MQTT)

Optional, off by default. Turn on *Publish "place" and "distance today" sensors* and, if you
use the Mosquitto app, nothing else is needed: the broker is found automatically. For each
tracked device Home Assistant gets:

- `sensor ... place`: the name of the place or zone the device is at (or *Away*)
- `sensor ... distance today`: miles moved today
- a `device_tracker` too, for external devices

They are created with MQTT discovery and permanent unique IDs, so you can rename them and use
them in automations. If you use an external broker, fill in its host, port, username and
password.

## Backups

Everything lives in the app's `/data`, which is included in Home Assistant backups. The app is
set to stop briefly during a backup so the database is copied safely, so a few minutes of points
may be missed while a backup runs.

## Troubleshooting

- **Location sensor unavailable**: check MQTT. The Location page shows `Mode: MQTT` or `REST (no unique ID)`.
- **Someone shows `unknown`**: wrong entity ID. Check Developer Tools, States.
- **Alerts never send**: check Alerts > Activity for "skipped" reasons (cooldown, time window, paused) and that the AI entity and notify service are set on the Notifications page.

**The map is empty.** Open *Settings > Tracked devices* and make sure at least one device is
ticked. If the page says it is not connected to Home Assistant, check the app log.

**A device never updates.** Mini Tracker only sees what Home Assistant sees. Check that the
entity itself updates in *Developer tools > States* and has `latitude` and `longitude`.

**An icon is blank or shows initials.** Open *Settings > Display*: it says how many SVGs were found in
your icons folder and lists every icon set that is available. Check the prefix (`mdi:`, `local:`, or your
Auto Custom Icons prefix) and the file name (`name.svg` is `local:name`). Use **Pick** to see exactly what
exists.

**The dashboard iframe is blank.** Usually the https/http mix described above. Test the 8100
URL in its own browser tab first.

**Stops look wrong.** Adjust *A stop is at least* and *Stop radius* under *Recording & stops*.
A bigger radius merges nearby stops.

**Log shows MQTT errors.** Install and start the Mosquitto broker app, or enter your broker
details manually.

Set the log level to `debug` in the app's Configuration tab for more detail.

## What it does not do

- It does not talk to Apple, Google or any cloud service for locations. It only reads Home
  Assistant. (Your map tiles are fetched from the tile server you choose.)
- It does not do street-address lookups. Name your stops with **Save as place** instead.
