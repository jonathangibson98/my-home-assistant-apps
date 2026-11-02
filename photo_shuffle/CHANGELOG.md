# Changelog

## 1.0.2

- Fix: add-on did not appear in the add-on store because `config.yaml` had an empty `url`; now points at the repository
- Fix: add-on no longer exits if the MQTT broker is not ready at startup, it retries every 15 seconds
- Clearer startup log (number of shuffles loaded and MQTT broker used)

## 1.0.1

- Version bump

## 1.0.0

- Initial release
- Unlimited folder shuffles, each exposed as its own device with an image entity
- "Next photo" button per shuffle
- No-repeat random order (reshuffles once the whole folder has been shown)
- Optional recursive scanning of subfolders
- Automatic resize/re-encode to JPEG (configurable size and quality)
- Automatic MQTT discovery using the Mosquitto add-on, or manual MQTT settings
- Entities are removed automatically when a shuffle is deleted from the config
