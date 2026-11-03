# Photo Hub

Turns pictures into Home Assistant **image entities**, from two sources:

- **Folders**: shuffles that rotate through the photos in a folder on a timer.
- **Unsplash**: collections of random [Unsplash](https://unsplash.com) photos, found by search terms you choose.

Both publish through **MQTT discovery**. There is no custom integration to install and nothing is written to `/share`. You manage everything from the web UI in the sidebar, and the Configuration tab only holds the settings listed below.

## Requirements

- The **MQTT integration** and a broker (the Mosquitto add-on is detected automatically).
- For folder shuffles: pictures under `/media`, `/share`, `/homeassistant` or `/addon_configs` (all mounted read-only).
- For Unsplash: a free Access Key (see below).

## Quick start

1. In **Configuration**, list the paths the add-on may read, pick picture formats and, if you want Unsplash, paste your Access Key. Save and start the add-on.
2. Turn on **Show in sidebar** and open **Photo Hub**.
3. **Folders** tab: tap **+ Add shuffle**, name it, **Browse** to a folder, set how often it changes, **Save**.
4. **Unsplash** tab: tap **+ Add collection**, name it, enter one search term per line, choose Landscape, Portrait or Both, **Save**. The first photos are pulled straight away.

## Entities and devices

| Source | Entity ID | Device |
|---|---|---|
| Folder shuffle `Family` | `image.family` | Photo Shuffle |
| Unsplash collection `Ocean`, landscape | `image.ocean_photos_landscape` | Unsplash Photos |
| Unsplash collection `Ocean`, portrait | `image.ocean_photos_portrait` | Unsplash Photos |

The entity ID is created from the name when you add the shuffle or collection. Renaming later changes the name, not the entity ID.

Unsplash entities also carry the attributes `photographer`, `photo_url` and `search_term`. Unsplash asks apps to credit photographers, so consider showing them on your dashboard.

Picture card:

```yaml
type: picture-entity
entity: image.ocean_photos_landscape
show_name: false
show_state: false
```

## Folders tab

Each shuffle is a card with the current picture, the folder, the picture count, what is showing now and when it changes next.

| Button | What it does |
|---|---|
| Next | Show another picture right away (also works while paused) |
| Pause / Resume | Stop or restart the timer. The last picture stays on the entity |
| Edit | Change the name, folder, interval, subfolders or enabled state |
| Delete | Remove the shuffle and its Home Assistant entity |

| Field | Description |
|---|---|
| Name | Display name, and the source of the entity ID. |
| Folder | Must be inside one of the allowed photo paths. |
| Change picture every | 5 seconds to 24 hours. |
| Include subfolders | Also use pictures in folders inside this folder. |
| Enabled | Untick to pause. |

Pictures are shown in random order **without repeats** until the whole folder has been used, then the order is reshuffled. The folder is rescanned whenever the order runs out, so new pictures are picked up automatically. Hidden files and folders (starting with `.`) are skipped.

## Unsplash tab

### Get an Access Key

1. Go to <https://unsplash.com/developers>, sign in and choose **Your apps > New Application**.
2. Accept the terms and give it a name.
3. Copy the **Access Key** (not the Secret Key) into the `unsplash_access_key` option and restart the add-on.

A new app is in "Demo" mode, which allows 50 requests per hour.

### Collections

| Field | Description |
|---|---|
| Name | Becomes part of the entity ID. Letters and numbers are best. |
| Search terms | One per line. A random one is used each time a photo is pulled, so several related terms give variety. |
| Orientation | Landscape, Portrait, or Both (two entities, updated separately). |

Every image costs one Unsplash request per refresh, so a collection set to Both costs two. The header shows your estimated requests per hour and warns you when you get close to 50. **Fetch now** on a card and **Fetch all now** pull new photos immediately, outside the normal schedule.

The refresh schedule survives restarts, so restarting the add-on does not burn requests. Only entities that have never had a photo are filled straight away.

## Configuration

### Option: `photo_paths`

The folders folder shuffles may read. Each must start with `/media`, `/share`, `/homeassistant` or `/addon_configs`. Use a specific path such as `/media/photos` to keep the add-on out of everything else.

### Option: `formats`

Picture types folder shuffles include: `jpg`, `png`, `webp`, `gif`, `bmp`, `tiff`. `jpg` covers `.jpg` and `.jpeg`. Animated GIFs use their first frame.

### Options: `max_dimension`, `jpeg_quality`

Longest side in pixels (320 to 4096, default 1920) and JPEG quality (30 to 100, default 85) of every picture published, from folders and from Unsplash.

### Options: `unsplash_access_key`, `unsplash_interval_minutes`, `unsplash_image_size`

Your Access Key, how often (5 to 1440 minutes, default 60) every collection gets a new photo, and which Unsplash size to download: `small` (about 400px), `regular` (about 1080px, default) or `full` (original, can be 10 MB or more; it is resized before publishing).

### Options: `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password`

Only needed if you are not using the Mosquitto add-on.

Changing options needs an add-on restart. Shuffles and collections are not affected by it.

## Behaviour

- The last picture of every entity is retained on the broker, so entities show an image straight after a Home Assistant restart.
- Shuffles and collections are saved in the add-on's own storage, so they survive restarts and updates, and are included in add-on backups.
- The web UI works even if the MQTT broker is down, and the add-on reconnects automatically. Pictures are held back until it is back.

## Upgrading

### From Photo Shuffle 2.x

Install this version over it. The slug is unchanged, so your shuffles, entity IDs and dashboards carry over as they are.

### From Photo Puller (add-on plus integration)

1. Note your collections (name, search terms, orientation) and re-add them on the **Unsplash** tab. They are not imported.
2. **Remove the Photo Puller integration** from Settings > Devices & services, and uninstall the old Photo Puller add-on. Do this before adding the collections, otherwise Home Assistant gives the new entities IDs ending in `_2`.
3. Use the same collection names and the entity IDs stay the same (`image.ocean_photos_landscape`).

The old `photo_puller_updated` event is no longer fired. Automations that used it can trigger on the image entity's state change instead.

## Troubleshooting

| Problem | Fix |
|---|---|
| Browse shows "No photo paths" | Add paths in Configuration and restart the add-on. |
| "Folder is outside the allowed photo paths" | Add a path that contains the folder to `photo_paths` and restart. |
| "No pictures found" | Check the `formats` option and whether Include subfolders should be on. |
| MQTT badge is red or orange | Make sure the Mosquitto add-on is running and the MQTT integration is set up. |
| Entities never appear | Wait for the MQTT badge to turn green, then check Settings, Devices & services, MQTT. |
| "No Unsplash Access Key" | Add the key in Configuration, Save and restart the add-on. |
| "Unsplash says the Access Key is bad (401)" | You probably copied the Secret Key, or there is a stray space. Use the Access Key. |
| "Unsplash rate limit hit (403)" | You used the 50 requests per hour. Raise `unsplash_interval_minutes` or trim collections. |
| Unsplash entity IDs end in `_2` | The old Photo Puller integration is still installed. Remove it, delete the stale entities and re-add the collection. |
| Image looks stale on a dashboard | Reload the dashboard. The entity updates on every interval. |
| Entity left behind after deleting a shuffle or collection | Delete it in Settings, Devices & services, MQTT. |
