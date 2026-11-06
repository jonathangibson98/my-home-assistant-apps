# Changelog

## 2.2.1 - 2026-11-06

- Fix: updating from 2.1.1 failed with "unauthorized" because Home Assistant tried to download a prebuilt image that is not available. The add-on now builds on your Home Assistant instead, like SVG Maker

## 2.2.0 - 2026-11-05

- **SVG Maker is now its own add-on** (`svg_maker`) and its tab and `svg_*` options are removed here. Photo-to-SVG conversion crashed the tracer inside this add-on, so it now runs on its own Debian-based image
- This add-on no longer installs Pillow or vtracer, so it builds faster and is smaller
- Everything else (Build, Announcements, Backup) is unchanged

## 2.1.1 - 2026-11-03

- Fix: converting a photo to SVG could crash the whole add-on (the panel then showed 503 Bad Gateway). Tracing now runs in a separate process, so a crash only fails that one conversion and shows a clear error

## 2.1.0 - 2026-11-03

The add-on is now **Creator & AI Builder** (same slug, so upgrading in place keeps everything).

- New **SVG Maker** tab with everything from SVG Maker 1.4.0: crop editor (drag, pinch, zoom; circle, rounded, square, full), auto-crop suggestion, auto-enhance, color or black and white tracing, detail slider, Save locally / Download / Both, icon-friendly names, black and white icons that follow Home Assistant colors, unique clip ids, temp-folder auto-save with optional auto-delete, name-conflict handling and HA `/local/` URLs
- SVG Maker options are now `svg_*` options (`svg_output_path`, `svg_temp_path`, `svg_auto_delete_temp`, `svg_auto_delete_after_days`, `svg_filename_style`, `svg_on_name_conflict`, `svg_default_mode`, `svg_default_detail`, `svg_path_style`, `svg_max_image_dimension`, `svg_max_upload_mb`, `svg_icon_names`, `svg_bw_follow_theme`, `svg_crop_editor`, `svg_auto_crop`, `svg_crop_shape`, `svg_crop_padding`, `svg_output_size`, `svg_auto_enhance`) with the same defaults. Copy over any you changed in the old add-on
- New **Backup** tab: save a backup to, and import a backup from, the new `backup_path` option (a folder or a single `.json` file). Imports save a safety copy first. New `backup_keep` option
- New `log_level` option (from SVG Maker) now applies to the whole add-on
- The add-on now maps `/share`, `/media`, `/backup`, `/ssl` and its own config folder as well, so SVG and backup paths can point there
- Option names and descriptions now show in the Configuration tab (new `translations/en.yaml`)
- Tab bar scrolls sideways on narrow screens

## 2.0.0 - 2026-11-03

AI Builder and Announcement Maker are now one add-on.

- New **Announcements** section with everything from Announcement Maker 0.4.0: info sources, personalities, TTS / Alexa / phone output, test before saving, helper tab, settings with entity pickers, export/import
- New Build / Announcements switch at the top of the panel; each page stays loaded while you switch
- One shared AI task entity, one Home Assistant connection, one sidebar entry
- Pushed announcements show in "Made so far"
- New options `ha_token`, `ha_url` and `helper_ai_task_entity` (all optional, from Announcement Maker)
- Only the Home Assistant ingress gateway can reach the web server (Builder previously accepted any caller on the add-on network)
- Same slug (`ai_builder`), so upgrading in place keeps your template entities and history. Announcement Maker settings do not carry over; use Export in the old add-on and Import here

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
