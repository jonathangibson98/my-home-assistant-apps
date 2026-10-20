# AI Builder

Type what you want in plain English. Your Home Assistant `ai_task` entity builds it.

AI Builder is a Home Assistant add-on with a sidebar web UI. You describe an automation, script, template sensor or helper, it asks your AI task entity to write the config, shows you what it made, and creates it in Home Assistant when you tap **Create**.

## What it can build

- **Automations**, new or edits to ones you already have
- **Template sensors and binary sensors**, test-rendered against your live data before you create them
- **Scripts**
- **Helpers**: input_boolean, input_number, input_select, input_text, input_datetime, counter, timer
- **Multi-part requests**, such as helpers + a template sensor + an automation from one sentence

## Features

- Works on your phone (built for the HA companion app)
- Checks every entity the AI uses against your real entity list and flags ones that don't exist
- Revise box: tell it what to change and it rewrites the config
- "Ask AI to fix it" button when Home Assistant rejects something
- Lists what it has created, and lets you delete the template entities it manages
- No cloud service of its own. It only talks to your Home Assistant

## Install

1. Copy the `ai_builder` folder into `/addons/` on your Home Assistant.
2. Settings -> Add-ons -> Add-on Store -> menu (three dots) -> **Check for updates**.
3. Open **AI Builder** under Local add-ons, then **Install** and **Start**.
4. Turn on **Show in sidebar**.

Template sensors need a one-time `configuration.yaml` change, and the file location is configurable. See [DOCS.md](DOCS.md).

## Requirements

- Home Assistant OS or Supervised (needs the add-on system)
- Home Assistant 2025.8 or newer (for `ai_task`)
- A working `ai_task` entity. The default is `ai_task.gemini_pro_ai_task`

## Support

AI output can be wrong. Always read the config before you create it.
