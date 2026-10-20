# AI Builder

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

### Changing something that exists

Use the **Change something that already exists** dropdown. It lists your UI-created automations, scripts, and the template entities this add-on made. Pick one, describe the change, and the AI gets the current config to edit. The result overwrites the original when you tap **Save changes**.

Scripts and automations written directly in YAML can't be loaded this way.

## Configuration

| Option | Default | Description |
|---|---|---|
| `ai_task_entity` | `ai_task.gemini_pro_ai_task` | The AI task entity used to write configs |
| `request_timeout` | `180` | Seconds to wait for the AI before giving up (30 to 600) |
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

**Add-on log**: Settings -> Add-ons -> AI Builder -> Log.

## Privacy

Your request, plus a trimmed list of entity IDs, names, and states relevant to it, is sent to your configured `ai_task` entity. If that entity uses a cloud model, that data goes to that provider. The add-on itself sends nothing anywhere else.
