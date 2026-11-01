# AI Builder

Builds Home Assistant things from plain English: automations, scenes, scripts, template sensors, helpers, AppDaemon apps, pyscripts, blueprints, and whole add-ons.

## How to use it

1. Open **AI Builder** from the sidebar.
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

### Safety for files and code

AppDaemon apps, pyscripts and add-ons are real code that runs on your system. Read it before you tap Create. The add-on also:

- Checks Python for syntax errors and blocks creating broken code
- Refuses to write outside its allowed folders
- Never overwrites a file without asking. If it exists, you get an **Overwrite it** button
- Keeps a backup of every file it overwrites, in the add-on's own `/data/backups` folder

### Changing something that exists

Use the **Change something that already exists** dropdown. It lists your UI-created automations, scenes, scripts, the template entities this add-on made, your AppDaemon `.py` files, your pyscript files, and your local add-ons. Pick one, describe the change, and the AI gets the current config to edit. The result overwrites the original when you tap **Save changes**.

Scripts, scenes and automations written directly in YAML can't be loaded this way. For AppDaemon and pyscript, only the code is changed. For add-ons, it only rewrites the files the AI changed and asks it to bump the version.

## Configuration

| Option | Default | Description |
|---|---|---|
| `ai_task_entity` | `ai_task.gemini_pro_ai_task` | The AI task entity used to write configs |
| `request_timeout` | `180` | Seconds to wait for the AI before giving up (30 to 600) |
| `appdaemon_apps_dir` | `/addon_configs/a0d7b954_appdaemon/apps` | Your AppDaemon apps folder. Must be under `/addon_configs` or your HA config folder |
| `template_file` | `ai_builder/package.yaml` | Where template sensors are written, relative to your Home Assistant config folder. Must end in `.yaml` |

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

**Add-on log**: Settings -> Add-ons -> AI Builder -> Log.

## Privacy

Your request, plus a trimmed list of entity IDs, names, and states relevant to it, is sent to your configured `ai_task` entity. If that entity uses a cloud model, that data goes to that provider. The add-on itself sends nothing anywhere else.
