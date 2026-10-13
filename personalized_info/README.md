# Personalized Info

Edit everyone's info and music preferences from a clean, phone-friendly UI inside Home Assistant. Everything saves to one readable YAML file, so if something crashes you still have your data.

## Features

- **People tab**: a collapsible card per person (household and friends). Add, edit, or delete fields, lists, and groups.
- **Music tab**: genres and artists for each person, one per line.
- **Other tab**: any leftover sections that you want to add.
- **Crash-proof storage**: all data lives in `/homeassistant/ai_memory/people.yaml`. You can hand-edit it.
- **Automatic backups**: every save copies the previous file into `/homeassistant/ai_memory/backups/` (last 5 kept).

## Install

1. Download this repo to your apps `/addons/personalized_info/`.
2. Settings → Apps → Install app → ⋮ → Check for updates.
3. Install **Personalized Info** from Local apps, start it, and turn on **Show in sidebar**.

## Restore from a crash

Copy any file from `/homeassistant/ai_memory/backups/` over `/homeassistant/ai_memory/people.yaml`, then restart the app.

## Restart saved info file

Delete `people.yaml`,`music.yaml`,`places.yaml` and restart the app. It will rebuild in `/homeassistant/ai_memory/*.yaml`.
