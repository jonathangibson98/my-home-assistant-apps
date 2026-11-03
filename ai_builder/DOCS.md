# Creator & AI Builder

Builds Home Assistant things from plain English (automations, scenes, scripts, template sensors, helpers, AppDaemon apps, pyscripts, blueprints, whole add-ons), makes AI voice announcements, turns photos into SVG icons, and backs up its own data. Use the tab bar at the top of the panel: **Build / Announcements / SVG Maker / Backup**.

# Build

## How to use it

1. Open **Creator & AI Builder** from the sidebar.
2. Type what you want. Be specific about devices, times, and conditions.
3. Pick a type, or leave it on **Let AI decide**.
4. Tap **Build it**. Gemini-style backends can take a minute or two.
5. Read the result. Tap **See the config** to view it.
6. Tap **Create**. Use **Create everything** if there are several items.

Not right? Type a change in the box under the results and tap **Revise**.

### Example requests

- "When the entry temperature is over 76 and someone is home, run the fans for 20 minutes, then stop. Add a switch to override it."
- "Template sensor that shows how many lights are on in the house."
- "Script that turns off all lights and locks the front door, called Goodnight."
- "Helper to hold a target temperature between 65 and 80."

### What each type does

| Type | What it makes | Where it goes |
|---|---|---|
| Automation | Automation | HA, Settings -> Automations |
| Scene | Scene | HA, Settings -> Scenes |
| Script | Script | HA, Settings -> Scripts |
| Template sensor | Sensor or binary sensor | The `template_file` path |
| Helper | input_boolean, input_number, input_select, input_text, input_datetime, counter, timer | HA, Settings -> Helpers |
| AppDaemon app | A Python app plus its config | `apps/ai_builder/<name>.py` and `.yaml` under `appdaemon_apps_dir` |
| Pyscript | A pyscript file | `/config/pyscript/<name>.py` |
| Blueprint | An automation or script blueprint | `/config/blueprints/<domain>/ai_builder/` |
| Add-on | A full local add-on (config, Dockerfile, run.sh, docs) | `/addons/<slug>/` |

**AppDaemon**: new apps go in an `ai_builder` subfolder with their own `.yaml`, so your existing `apps.yaml` is never touched. AppDaemon reloads on its own. Check the AppDaemon log afterward.

**Pyscript**: needs the Pyscript integration installed (the `/config/pyscript` folder must exist). The add-on calls `pyscript.reload` after writing.

**Add-ons**: after creating one, go to Settings -> Add-ons -> Add-on Store -> menu -> Check for updates, then open it under Local add-ons. The add-on checks that `config.yaml` is valid, Python files parse, and warns if `run.sh` uses `with-contenv` without `init: false`.

### Add-on auto-fixes

AI-written add-ons break in predictable ways, so the add-on knows what works on your system and repairs these before you create anything. Each fix is shown on the card as "Fixed automatically".

- Per-architecture base images like `amd64-base` (fail with "no match for platform") are replaced with `ghcr.io/home-assistant/base:latest`
- A leftover `build.yaml` is removed
- `run.sh` gets the `#!/usr/bin/with-contenv bashio` first line, and `config.yaml` gets `init: false`
- `pip install` gets `--break-system-packages`, and a missing `chmod` on `run.sh` is added
- Unquoted versions are quoted, old 32-bit architectures are dropped, and old folder-map names are corrected

It also blocks creation when `config.yaml` has bad schema types, options missing from the schema, invalid `map` entries, or a bad `startup`/`boot` value.

If an add-on you already have fails to build, pick it in the **Change something that already exists** dropdown, paste the build error from the Supervisor log into your request, and create the fix.

### Safety for files and code

AppDaemon apps, pyscripts and add-ons are real code that runs on your system. Read it before you tap Create. The add-on also:

- Checks Python for syntax errors and blocks creating broken code
- Refuses to write outside its allowed folders
- Never overwrites a file without asking. If it exists, you get an **Overwrite it** button
- Keeps a backup of every file it overwrites, in the add-on's own `/data/backups` folder

### Changing something that exists

Use the **Change something that already exists** dropdown. It lists your UI-created automations, scenes, scripts, the template entities this add-on made, your AppDaemon `.py` files, your pyscript files, and your local add-ons. Pick one, describe the change, and the AI gets the current config to edit. The result overwrites the original when you tap **Save changes**.

Scripts, scenes and automations written directly in YAML can't be loaded this way. For AppDaemon and pyscript, only the code is changed. For add-ons, it only rewrites the files the AI changed and asks it to bump the version.

## Configuration (applies to the whole add-on)

| Option | Default | Description |
|---|---|---|
| `ai_task_entity` | `ai_task.gemini_pro_ai_task` | The AI task entity used to write configs |
| `request_timeout` | `180` | Seconds to wait for the AI before giving up (30 to 600) |
| `appdaemon_apps_dir` | `/addon_configs/a0d7b954_appdaemon/apps` | Your AppDaemon apps folder. Must be under `/addon_configs` or your HA config folder |
| `ha_token` | blank | Optional long-lived token. Leave blank unless the default Supervisor access fails (Profile -> Security in Home Assistant) |
| `ha_url` | `http://homeassistant:8123` | Only used when `ha_token` is set |
| `helper_ai_task_entity` | blank | Optional separate AI task entity for the Announcements helpers. Blank uses the Announcements AI Task |
| `template_file` | `ai_builder/package.yaml` | Where template sensors are written, relative to your Home Assistant config folder. Must end in `.yaml` |
| `log_level` | `info` | `debug`, `info`, `warning` or `error`. Applies to the whole add-on |
| `backup_path` | `/share/ai_builder_backups` | Where Backup saves and imports. A folder, or a single `.json` file. See Backup below |
| `backup_keep` | `20` | Folder mode: keep the newest this many backups, delete older ones |

SVG Maker options are listed in the SVG Maker section below.

Restart the add-on after changing options.

## One-time setup for template sensors

By default the file is `ai_builder/package.yaml`. You can change it with the `template_file` option. The add-on creates the folder if it doesn't exist.

Automations, scripts, and helpers work immediately. Template sensors are written to the `template_file` path, which Home Assistant has to be told to load. Add this to `configuration.yaml`:

```yaml
homeassistant:
  packages:
    ai_builder: !include ai_builder/package.yaml
```

If you already have a `homeassistant:` section with `packages:`, add only the `ai_builder:` line under it. Do not create a second `homeassistant:` key.

**If you load a whole packages folder** with `packages: !include_dir_named packages`, don't add the line above. Instead set `template_file` to a file inside that folder, for example `packages/ai_builder.yaml`. The add-on notices the folder include and stops showing the banner. Don't put both a folder include and an explicit `ai_builder:` entry under `packages:`, because that breaks the folder include.

If you change `template_file` later, move or delete the old file yourself, then restart Home Assistant once.

Restart Home Assistant once. After that, new or changed template sensors apply instantly with no restart.

The add-on shows a yellow banner until this is detected.

## Where things go

| Type | Where it is stored | Where you manage it later |
|---|---|---|
| Automation | Home Assistant's automations | Settings -> Automations |
| Script | Home Assistant's scripts | Settings -> Scripts |
| Helper | Home Assistant helpers | Settings -> Helpers |
| Template entity | The `template_file` path (default `/config/ai_builder/package.yaml`) | This add-on, "Made so far" tab |

Don't hand-edit the template file. The add-on rewrites it.

## Checks the add-on does for you

- **Unknown entities**: any entity ID in the config that Home Assistant doesn't have is flagged.
- **Template preview**: the state template is rendered against live data. Errors show in red.
- **Home Assistant validation**: if HA rejects the config when you create it, the error is shown with an **Ask AI to fix it** button.

None of this guarantees the automation does what you meant. Read the config before creating anything that controls many devices, locks, or heating and cooling.

## Troubleshooting

**"I can't find ai_task.xxx"**: fix `ai_task_entity` in the Configuration tab to match your entity ID.

**"The AI answered, but not in a usable format"**: the model didn't return clean JSON. Tap Build again or reword. Unofficial or cookie-based AI backends do this more often.

**Request times out**: raise `request_timeout`.

**Template sensor doesn't appear**: check the one-time setup above, then restart Home Assistant.

**Create fails with a validation message**: tap **Ask AI to fix it**, or edit the request and revise.

**"AppDaemon folder not found"**: set `appdaemon_apps_dir` to your apps folder. If AppDaemon's files are in your config folder, use something like `/config/appdaemon/apps`.

**Long code gets cut off or isn't valid JSON**: add-ons are big outputs. Raise `request_timeout`, and consider asking for one add-on at a time.

**Add-on log**: Settings -> Add-ons -> Creator & AI Builder -> Log.

## Privacy

Your request, plus a trimmed list of entity IDs, names, and states relevant to it, is sent to your configured `ai_task` entity. If that entity uses a cloud model, that data goes to that provider. The add-on itself sends nothing anywhere else.

---

# Announcements

All announcement setup happens inside the app, on the **Settings** tab of Announcements, not in this Configuration tab.

- Each field is a search box limited to the right entity type. Tap one, pick an entity, it becomes a chip. Tap the chip to remove it.
- **Auto-fill empty** fills single-choice fields that only have one match.
- **Info sources** cover anything else: label, entity, optional attribute (concerts, sports, PS5...), or a custom template.
- **Export / Import** moves your settings as JSON. `examples/announcement-settings.json` is a filled-in example.
- Required to generate: AI Task, text-to-speech engine, main speaker. The AI Task defaults to this add-on's `ai_task_entity`.
- The personality dropdown (optional) needs an `input_select` with options `Hype`, `Roast`, `Sweetie Pie`.

## Announcement tabs

- **Create:** pick data, personality, then type **What should it do?** in plain words. Every data source is loaded into a variable (`src_<name>`) in the script, and the AI Task reads those variables.
- **Test before saving:** runs a temporary copy of the script and deletes it afterward, so nothing lands in your Scripts list. *Preview data only* skips the AI and speaking, and shows what each source rendered. *Test (text only)* also runs the AI and shows what it would say. *Test with sound* speaks it too. If a step fails, the error from Home Assistant is shown.
- **Push to Home Assistant** writes the script (it then appears in Settings -> Scripts and in Build's history).
- **Helper:** (1) describe what you want and the AI writes the instructions and ticks the data it needs; (2) test an entity and add it as an info source.
- **Settings:** your entities and notify targets, plus info sources. Each source has a template you can edit to fix it, and a reset button to go back to the auto-generated one.

Phone notifications: entities (`notify.jon`) and services (`notify.mobile_app_*`, shown as "service") both work, and you can type an id that isn't listed.

Saved setups (the **Save setup** button) are stored in your browser, not in the add-on.

## Announcement troubleshooting

**Push to Home Assistant fails**: check the Log tab. If Home Assistant refuses the default Supervisor access, set `ha_token`.

**No entities in the pickers**: you can still type an entity id into any field.

## Security

Only the Home Assistant ingress gateway can reach this add-on's web server, so other add-ons and devices on your network can't call it directly.

---

# SVG Maker

Turn photos into scalable SVG vector files from the **SVG Maker** tab.

## How to use
1. Pick a photo. A crop window appears with the suggested crop already in place.
2. Drag the photo to move it, pinch or use the Zoom slider to resize. Choose **Circle**, **Rounded**, **Square** or **Full** (whole photo). **Auto-fit** re-runs the suggestion and **Reset** starts over.
3. Choose **Color** or **Black & white**, set the detail, and tap **Convert to SVG**.
4. Preview the result, type the file name you want, then tap **Save locally** (to your save folder), **Download** (to your device) or **Both**.

**Auto-crop** finds whatever stands out most and centers the crop on it. It is not face detection, so check it and nudge if needed. **Auto-enhance** boosts contrast, smooths texture and simplifies colors so photos trace into clean shapes and smaller files. The crop is made in your browser, so phone photos in formats like HEIC also work if your browser can open them.

Every conversion is also auto-saved to the temp folder (`svg_temp_path`). Save locally or Both moves that copy into your save folder, so only unsaved results stay in temp. Files under `/homeassistant/www` are available in Home Assistant at `/local/...`, for example `/local/svg_maker/temp_icons/name.svg`. If `www` did not exist before, restart Home Assistant once so it starts serving `/local`.

## File access
The add-on can see `/homeassistant`, `/share`, `/media`, `/backup`, `/ssl`, `/addons`, `/config` (its own config) and `/addon_configs`. SVG Maker only writes to the save and temp folders you set. Protected system paths are refused.

## SVG options

| Option | Default | What it does |
|---|---|---|
| `svg_output_path` | `/homeassistant/custom_icons` | Where Save locally and Both put files. The default is the folder the Custom Icons integration reads. Created automatically |
| `svg_temp_path` | `/homeassistant/www/svg_maker/temp_icons` | Auto-save location for results you did not save |
| `svg_auto_delete_temp` | `false` | Delete old files the tool made from the temp folder. Never touches the save folder |
| `svg_auto_delete_after_days` | `7` | Age limit when auto-delete is on |
| `svg_filename_style` | `original_timestamp` | Naming for temp files (`original`, `timestamp`, `original_timestamp`) |
| `svg_on_name_conflict` | `rename` | `rename` adds -1, -2. `overwrite` replaces |
| `svg_default_mode` | `color` | Starting color mode on the page |
| `svg_default_detail` | `5` | Starting detail (1 to 10) |
| `svg_path_style` | `spline` | `spline`, `polygon` or `none` |
| `svg_max_image_dimension` | `1600` | Longest side in pixels before tracing |
| `svg_max_upload_mb` | `25` | Largest upload allowed |
| `svg_icon_names` | `true` | Saves names as lowercase-with-hyphens so they work as icon names |
| `svg_bw_follow_theme` | `true` | Black and white results use currentColor so Home Assistant can recolor them |
| `svg_crop_editor` | `true` | Show the drag and zoom crop window after you pick a photo |
| `svg_auto_crop` | `true` | Auto-suggest the crop. With the editor off, the auto crop is applied without asking |
| `svg_crop_shape` | `circle` | `circle`, `rounded`, `square` or `none` (whole photo). Changeable on the page |
| `svg_crop_padding` | `15` | Extra space around the detected subject, in percent |
| `svg_output_size` | `512` | Cropped photo is shrunk to this many pixels before tracing |
| `svg_auto_enhance` | `true` | Contrast, noise smoothing and color simplifying before tracing. Changeable on the page |

Restart the add-on after changing options.

## SVG tips
- Works best on logos, drawings, signatures and images with clear shapes.
- iPhone photo failing? Settings, Camera, Formats, **Most Compatible** (HEIC is not supported).
- Slow on a Raspberry Pi? Lower `svg_max_image_dimension` or the detail slider. Conversions run one at a time.

## Using your icons in Home Assistant
Install the **Custom Icons** integration (HACS), enable the **Local** collection in its configuration, and press **RELOAD** after saving new icons. Icons are then available as `local:<file-name>`. Full-color icons keep their colors. Black and white icons follow the entity color when `svg_bw_follow_theme` is on.

---

# Backup

The **Backup** tab saves and restores this add-on's own data:

- the template sensors it manages (and so the template file it writes)
- the "Made so far" history
- your Announcements settings

It does not back up your Home Assistant automations, scripts or helpers (use Home Assistant's own backups for those), saved SVG files, or the `/data/backups` copies of files the Builder overwrote.

## Choosing where backups go
Set `backup_path` in the Configuration tab and restart the add-on.

- **A folder** (default `/share/ai_builder_backups`): each **Save backup now** creates `ai_builder_backup_YYYYMMDD-HHMMSS.json`. The newest `backup_keep` of those are kept. The Import list shows every valid backup file in the folder, so you can also copy a backup in from elsewhere.
- **A single file** ending in `.json`, for example `/share/creator_backup.json`: each save overwrites that file, and Import reads it.

Use a path under `/share`, `/media`, `/backup` or `/homeassistant`. Anything stored only inside the add-on is deleted if you uninstall it. Protected system paths are refused and the default is used instead.

## Importing
Tap **Import** next to a backup, then tap again to confirm. Import **replaces** the current template sensors, history and announcement settings with the backup's. Before it changes anything it saves a safety copy named `ai_builder_backup_pre-import_...json` in the same place, so you can import that one to undo. Damaged or non-backup files are rejected without changing anything. Template sensors are rewritten to the template file and reloaded straight away.

Moving to a new Home Assistant: install the add-on, set the same `backup_path` (or copy the file there), and import. Announcement Maker settings from the old standalone add-on are a different format; use its Export and the Announcements Import for those.
