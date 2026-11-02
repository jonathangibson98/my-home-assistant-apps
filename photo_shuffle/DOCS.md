# Photo Shuffle

Turn folders of pictures into Home Assistant **image entities** that change to a random photo on a timer. You manage the shuffles from a web UI in the sidebar, and the Configuration tab only controls what the add-on is allowed to read.

## Requirements

- The **MQTT integration** and a broker (the Mosquitto add-on is detected automatically).
- Pictures somewhere under `/media`, `/share`, `/homeassistant` or `/addon_configs` (all mounted read-only).

## Quick start

1. In **Configuration**, list the paths the add-on may read and pick your picture formats. The defaults are `/media` and `/share`, with jpg, png and webp.
2. Start the add-on and turn on **Show in sidebar**.
3. Open **Photo Shuffle** in the sidebar and tap **+ Add shuffle**.
4. Give it a name, tap **Browse** to choose a folder, set how often it changes, and **Save**.

Each shuffle appears in Home Assistant as a device with:
- an image entity, for example `image.family`
- a button, for example `button.family_next_photo`

## The web UI

Every shuffle is a card showing the current picture, the folder, how many pictures were found, what is showing now, when it changed and when it will change next.

| Button | What it does |
|---|---|
| Next | Show another picture right away (also works while paused) |
| Pause / Resume | Stop or restart the timer. The last picture stays on the entity |
| Edit | Change the name, folder, interval, subfolders or enabled state |
| Delete | Remove the shuffle and its Home Assistant entities |

A red **Problem** badge means something is wrong, for example the folder is missing or has no pictures in the selected formats. The reason is shown on the card.

The **Activity** panel at the bottom shows what the add-on is doing: every picture change, warnings, and MQTT connection events.

### Shuffle settings

| Field | Description |
|---|---|
| Name | Display name. The entity ID is created from it when you add the shuffle (`Family` becomes `image.family`). Renaming later changes the name, not the entity ID. |
| Folder | Must be inside one of the allowed photo paths. |
| Change picture every | 5 seconds to 24 hours. |
| Include subfolders | Also use pictures in folders inside this folder. |
| Enabled | Untick to pause. |

## Configuration

### Option: `photo_paths`

The folders the add-on is allowed to read. Shuffles can only use folders inside these paths. Each must start with `/media`, `/share`, `/homeassistant` or `/addon_configs`. Add a more specific path, such as `/media/photos`, to keep the add-on out of everything else.

### Option: `formats`

Which picture types to include: `jpg`, `png`, `webp`, `gif`, `bmp`, `tiff`. `jpg` covers both `.jpg` and `.jpeg`. Animated GIFs use their first frame.

### Option: `max_dimension`

Longest side in pixels of the picture sent to Home Assistant (320 to 4096). Default 1920.

### Option: `jpeg_quality`

JPEG quality, 30 to 100. Default 85.

### Options: `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password`

Only needed if you are not using the Mosquitto add-on.

Changing options needs an add-on restart. Shuffles are not affected by it.

## Behaviour

- Pictures are shown in random order **without repeats** until the whole folder has been used, then the order is reshuffled. The same picture is never shown twice in a row across a reshuffle.
- The folder is rescanned whenever the order runs out, so new pictures are picked up automatically.
- Photos are rotated using their EXIF data, resized and sent as JPEG. Hidden files and folders (starting with `.`) are skipped, and files that fail to open are skipped.
- The last picture is retained, so entities show an image straight after a Home Assistant restart.
- Shuffles are saved in the add-on's own storage, so they survive restarts and updates, and are included in add-on backups.

## Using it

Picture card:

```yaml
type: picture-entity
entity: image.family
show_name: false
show_state: false
```

Skip to the next photo from an automation:

```yaml
action: button.press
target:
  entity_id: button.family_next_photo
```

## Troubleshooting

| Problem | Fix |
|---|---|
| Browse shows "No photo paths" | Add paths in Configuration and restart the add-on. |
| "Folder is outside the allowed photo paths" | Add a path that contains the folder to `photo_paths` and restart. |
| "No pictures found" | Check the `formats` option and whether Include subfolders should be on. |
| MQTT badge is red or orange | Make sure the Mosquitto add-on is running and the MQTT integration is set up. |
| Entities never appear | Wait for the MQTT badge to turn green, then check Settings, Devices & services, MQTT. |
| Image looks stale on a dashboard | Reload the dashboard. The entity updates on every interval. |
| Upgraded from 1.x | The old `shuffles` option is gone. Re-add your shuffles in the web UI. Use the same names and the entities keep their IDs. |
