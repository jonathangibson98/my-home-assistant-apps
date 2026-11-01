# Photo Shuffle

Turn any folder of pictures into a Home Assistant **image entity** that changes to a random photo on a timer. Add as many folders as you like; each one is an independent shuffle.

## Requirements

- The **MQTT integration** and a broker (the Mosquitto add-on is detected automatically).
- Your pictures somewhere under `/media` or `/share` (both mounted read-only).

## Quick start

1. Put pictures in a folder such as `/media/photos/family`.
2. Open the add-on **Configuration** tab and add a shuffle:

   ```yaml
   shuffles:
     - name: Family
       path: /media/photos/family
       interval: 60
       recursive: true
   ```
3. Start the add-on. A device called **Family** appears under Settings → Devices & services → MQTT, with:
   - `image.family` – the current picture
   - `button.family_next_photo` – shuffle immediately

## Configuration

### Option: `shuffles` (required)

A list. Add one entry per folder.

| Field | Description |
|---|---|
| `name` | Display name. Also determines the entity ID (`Family` → `image.family`). |
| `path` | Absolute folder path inside the add-on, e.g. `/media/photos/trip`. |
| `interval` | Seconds between pictures (5–86400). |
| `recursive` | `true` to include subfolders, `false` for the top level only. |

Names should be unique. If two share a name, the second gets a `_2` suffix.

### Option: `max_dimension`

Longest side of the published image in pixels (320–4096). Default `1920`. Lower it for wall tablets or slow networks.

### Option: `jpeg_quality`

JPEG quality 30–100. Default `85`.

### Options: `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password`

Optional. Only needed if you are **not** using the Mosquitto add-on. Leave empty to use the broker the Supervisor provides.

## Behaviour

- Pictures are shown in random order **without repeats** until every picture in the folder has been used, then the deck is reshuffled. It never shows the same picture twice in a row across a reshuffle.
- The folder is rescanned each time the deck runs out, so new pictures are picked up automatically.
- Supported formats: JPG, PNG, WebP, GIF (first frame), BMP. Files that fail to open are skipped.
- Photos are rotated according to EXIF data, resized, and published as JPEG.
- The last picture is retained, so entities show an image right after a Home Assistant restart.
- Removing a shuffle from the config removes its entities the next time the add-on starts.

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
| Log says `folder not found` | Check the path. Folders live under `/media` or `/share`, not `/config`. |
| Log says `no pictures found` | Check the extensions and whether `recursive` should be `true`. |
| Entities never appear | Make sure the MQTT integration is set up and the broker is running, then restart the add-on. |
| Image looks stale in a dashboard | Browsers cache aggressively; reload the dashboard. The entity itself updates on every interval. |
| Slow or failing updates with huge photos | Lower `max_dimension`. Very large retained MQTT messages can hit broker limits. |
