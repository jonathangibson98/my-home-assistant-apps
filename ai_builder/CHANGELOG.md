# Changelog

## 1.1.1 - 2026-11-01

- Fix: generated add-ons failed to build on aarch64 ("no match for platform in manifest") because the AI used an amd64 base image
- The AI is now told what works on this system (base image, run.sh, config.yaml rules, valid folder maps, template and code gotchas)
- Add-ons are auto-repaired before creation, with each fix shown; stricter config.yaml checks
- Fix: the add-on's own config used an invalid map name; it is now `all_addon_configs`

## 1.1.0 - 2026-11-01

- New types: scenes, AppDaemon apps, pyscripts, blueprints and full add-ons
- Edit existing scenes, AppDaemon `.py` files, pyscript files and local add-ons
- Python syntax checks and add-on `config.yaml` checks before anything is written; warns about the missing `init: false` crash
- Existing files are never overwritten without confirmation, and overwritten files are backed up to `/data/backups`
- New `appdaemon_apps_dir` option
- The add-on now maps `/addon_configs` and `/addons`

## 1.0.2 - 2026-10-20

- New `template_file` option: choose where template sensors are written (default stays `ai_builder/package.yaml`)
- Setup banner now recognizes `!include_dir_named`-style folder includes and shows your configured path

## 1.0.1 - 2026-10-20

- Fix: add-on failed to start with "s6-overlay-suexec: fatal: can only run as pid 1" (set `init: false`)

## 1.0.0 - 2026-10-20

First release.

- Sidebar web UI: describe what you want, review it, create it
- Builds automations, scripts, template sensors and binary sensors, and helpers
- Multiple items from a single request, with a "Create everything" button
- Edit existing automations, scripts, and the template entities it manages
- Live preview of template sensor values
- Flags entity IDs that don't exist in your Home Assistant
- Revise box and "Ask AI to fix it" after a failed create
- "Made so far" tab with history and template entity deletion
- Options for the AI task entity and request timeout
