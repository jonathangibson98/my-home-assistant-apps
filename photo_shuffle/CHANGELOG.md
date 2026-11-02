# Changelog

## 2.1.1

- Fix: shuffles created by earlier versions stayed on their own device (e.g. "Baby & Me") and the shared "Photo Shuffle" device stayed empty. Home Assistant never moves an existing MQTT entity to another device, so on first start the add-on now re-creates each entity once on the shared device
- Entity IDs are unchanged (`image.baby_me` stays `image.baby_me`)
- The old, now empty per-shuffle devices can be deleted from Settings, Devices & services, MQTT if Home Assistant leaves them behind

## 2.1.0

- All shuffle image entities now live under ONE device called "Photo Shuffle" instead of one device per shuffle
- Removed the MQTT "Next photo" button. Use the Next button in the web UI
- The old per-shuffle button entities are removed from Home Assistant automatically on start
- Entity IDs are unchanged (`image.family` stays `image.family`)
- Web UI Next now waits until the new picture is published, so the entity and the preview update right away

## 2.0.0

- New web UI (sidebar panel): add, edit, pause and delete shuffles, with a live preview of the current picture, picture counts, next-change countdown and an activity log
- Folder browser in the UI, limited to the paths you allow
- Configuration tab is now just: allowed photo paths, picture formats (jpg, png, webp, gif, bmp, tiff), image size and quality
- Shuffles are stored by the add-on and survive restarts and updates
- Entities keep the same IDs as before, so existing dashboards keep working
- Shuffles can be added or removed without restarting the add-on
- Entities are removed from Home Assistant when a shuffle is deleted
- Web UI works even if the MQTT broker is down; the add-on reconnects automatically

Breaking: the `shuffles` option was removed from Configuration. Re-add your shuffles in the web UI.

## 1.0.2

- Fix: add-on did not appear in the add-on store because `config.yaml` had an empty `url`
- Fix: add-on no longer exits if the MQTT broker is not ready at startup
- Clearer startup log

## 1.0.1

- Version bump

## 1.0.0

- Initial release
- Unlimited folder shuffles, each exposed as its own device with an image entity
- "Next photo" button per shuffle
- No-repeat random order
- Optional recursive scanning of subfolders
- Automatic resize and JPEG encoding
- MQTT discovery using the Mosquitto add-on, or manual MQTT settings
