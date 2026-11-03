# AI Builder

Type what you want in plain English. Your Home Assistant `ai_task` entity builds it. One add-on, two tools:

- **Build**: automations, scenes, scripts, template sensors, helpers, AppDaemon apps, pyscripts, blueprints and whole add-ons.
- **Announcements**: tap checkboxes to make AI-written voice announcements (weather, news, welcome home, roasts, whatever). It writes the Home Assistant script and pushes it in.

Use the **Build / Announcements** switch at the top of the sidebar panel.

## Build

- Automations and scenes, new or edits to ones you already have
- Template sensors and binary sensors, test-rendered against your live data before you create them
- Scripts, and helpers (input_boolean, input_number, input_select, input_text, input_datetime, counter, timer)
- AppDaemon apps, pyscripts and blueprints, with syntax checks before anything is written
- Whole add-ons: config, Dockerfile, run.sh and docs, written to `/addons`, auto-repaired for this system
- Multi-part requests, such as helpers + a template sensor + an automation from one sentence
- Flags entities the AI used that don't exist, "Revise" box, "Ask AI to fix it" when HA rejects something
- Never overwrites a file without asking, and backs up what it replaces

## Announcements

- Info sources: household, who is where, weather, news, calendars, to-do, trash, any entity or attribute, or a custom template
- Personalities (Hype, Roast, Sweetie Pie), or follow an `input_select` in Home Assistant
- Speak on a main speaker (TTS), Alexa speakers, and phone notifications; pause and resume music
- **Test before saving**: preview the data, test text only, or test with sound, using a temporary script that is deleted afterward
- Helper tab: describe what you want and the AI writes the instructions and ticks the data it needs
- Settings with searchable entity pickers, Auto-fill, and Export/Import as JSON

## How the two halves work together

- One AI task entity is shared. Announcements use it unless you pick a different one in Announcements > Settings
- Announcements you push show up in Build's **Made so far** history
- Announcement scripts are normal scripts, so you can pick one in Build's **Change something that already exists** and have the AI edit it
- One connection to Home Assistant, one entity list, one sidebar entry

## Install

1. Copy the `ai_builder` folder into `/addons/` on your Home Assistant (replace the old one if you are upgrading).
2. Settings -> Add-ons -> Add-on Store -> menu (three dots) -> **Check for updates**.
3. Open **AI Builder** under Local add-ons, then **Install** (or **Rebuild** if upgrading) and **Start**.
4. Turn on **Show in sidebar**.

Template sensors need a one-time `configuration.yaml` change. See [DOCS.md](DOCS.md).

## Requirements

- Home Assistant OS or Supervised (needs the add-on system)
- Home Assistant 2025.8 or newer (for `ai_task`)
- A working `ai_task` entity. The default is `ai_task.gemini_pro_ai_task`
- For announcements: a text-to-speech engine and a speaker. Alexa speakers need the `alexa_media` custom integration

## Support

AI output can be wrong. Always read the config or script before you create or push it.
