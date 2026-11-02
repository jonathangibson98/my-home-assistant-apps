# Changelog

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
