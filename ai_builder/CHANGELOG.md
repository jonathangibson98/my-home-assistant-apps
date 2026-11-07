# Changelog

## 2.8.0 - 2026-11-07

- **Import a whole automation as a fact.** Import my script now also takes an automation that does everything itself (asks the AI, then saves the result), like a daily birthdays automation. Paste the YAML (a single automation, a `- id:` item from `automations.yaml`, or one under `automation:`), or leave the box empty and pick one from the **Automation** dropdown. It is kept exactly as written and you edit the YAML in the editor
- If a pasted automation has the same name as one already in Home Assistant, it takes that one over, so pushing updates it instead of making a duplicate. A copy of the old one is saved first
- **Choose where the text file goes.** The editor lists every `topic:` in your automation as a field you can change, with a **Use my folder** button
- **New add-on option: Facts file path** (Configuration tab). Sets the MQTT folder for all facts, for example `file_reader/overwrite/`. When set, it wins over Facts > Settings, which then shows it as locked. Blank keeps the old behavior
- Automation-only facts have **Run now** (triggers the automation, skipping its conditions) and show whether the automation is on. Deleting one only forgets it here and never deletes it from Home Assistant

## 2.7.0 - 2026-11-07

- **Facts can keep your own automations.** Each fact now has a **Your own automation** card. Load an automation you already have from a dropdown (or paste YAML) and it is kept exactly as written and pushed with the fact's script. It works for generated facts and for imported scripts
- **Import my script** has a new **Automation that runs it** dropdown, so a script and its automation come in together
- Pushing over an automation that already exists saves a copy of the old one first, in `/data/automation_backups` inside the add-on
- Your own automations are never deleted by this add-on. Only the generated `<script id>_auto` schedule is removed when you turn the schedule off
- Library cards show whether your automation is in Home Assistant and on or off. Automations defined only in YAML files (no UI id) cannot be loaded, because Home Assistant cannot edit them from here

## 2.6.0 - 2026-11-07

- **New Facts tab**, next to Announcements. Make AI-written facts that are saved to a text file over MQTT (default topic prefix `file_reader/overwrite/`), such as a random trivia fact, a dark history fact, a music fact about an artist, or a fact about a city
- Same workflow as Announcements: **My facts** library (Edit, Run now, Duplicate, Delete, Update all), an editor with a test panel, a Helper tab that writes the instructions and random lists for you, Settings, and Import my script
- **Random lists** (topic, angle, genre, decade, anything you name) are picked on every run and told to the AI, with an optional random seed. Formats: just the fact, a title and the fact (`Title ||| fact`, split by the script), or a short list. Optional heading above the fact
- Rules you can switch on or off: real and verifiable, go obscure, keep the household out, don't repeat the last fact (reads your file sensor)
- **Optional schedule**: every N minutes or hours, and/or when an entity or attribute changes, only when someone is home. It is a separate automation (`<script id>_auto`) that this add-on creates, updates and removes
- Facts share the AI Task and data sources with Announcements, and are included in Backup and Restore
- Shared data-source code moved into `sources.js`; Announcements behaves the same

## 2.5.0 - 2026-11-06

- **Import your own script.** On **My announcements**, tap **Import my script** and paste any Home Assistant script (YAML). It works with just the script, the script with its id on top (as in `scripts.yaml`), or only the list of steps. You can also load a script that already exists in Home Assistant from a dropdown
- Imported scripts are kept **exactly as you wrote them** and get their own editor with the YAML, a name field (it keeps the `alias:` line in step), **Check YAML**, Save, **Save and push**, Run saved script and Copy YAML. They also work with Duplicate, Delete, Update all and Backup
- Type the id of a script you already have to **take it over**: pushing replaces it and automations that call it keep working
- **Switch to the form tools** reads an imported script into the form (instructions, speakers, volume, personalities) so you can use the helper and the test panel. Your own prompt is kept word for word. Anything the form does not cover is dropped when you push, so leave without saving to keep the original

## 2.4.0 - 2026-11-06

- **Announcements are now a library.** Every announcement you make is saved inside the add-on (not in the Configuration tab, which is for options like paths and entities) and listed under **My announcements** with status, Edit, Run now, Duplicate and Delete
- Edit any announcement and push it again. The script id stays the same, so automations that call it keep working. **Save** keeps changes here only, **Save and push** updates Home Assistant
- Scripts this tool made before this version show under **Made earlier, in Home Assistant**. Open one and the form is rebuilt from the script
- **Update all in Home Assistant** re-pushes every announcement with your current Settings (for example after you change the speaker)
- Setups saved in your browser can be moved into the library with one tap
- Saved announcements are included in Backup and Restore
- Web UI redesigned: one look across Build, Announcements and Backup (light and dark), an editor with four clear steps and a test panel beside it, Settings grouped into cards with a save bar, and consistent buttons, status pills and messages
- Delete buttons now need a second tap, and a delete from Announcements can also remove the script in Home Assistant (only scripts made by this add-on)

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
