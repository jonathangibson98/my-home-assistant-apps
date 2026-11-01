# Photo Shuffle

Each entry under `shuffles` becomes its own device in Home Assistant with:
- an **image entity** that changes to a random picture every `interval` seconds
- a **Next photo** button to shuffle on demand

Pictures are shown in random order without repeats until the whole folder has been used, then reshuffled.

## Options
- `shuffles`: list of `name`, `path`, `interval` (seconds), `recursive`
- `max_dimension`: longest side in px (default 1920)
- `jpeg_quality`: 30-100 (default 85)
- `mqtt_*`: optional, only if you don't use the Mosquitto add-on

Paths must be under `/media` or `/share`, e.g. `/media/photos/vacation`.
Requires the MQTT integration. Supports jpg, png, webp, gif (first frame), bmp.
