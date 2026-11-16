# Person Profiles

![Person Profiles](logo.png)

Builds one profile sensor for each person in Home Assistant from every entity linked to them. Other automations, dashboards and AI agents can read it. AI summaries and questions are optional.

## What you get

| Entity | What it holds |
| --- | --- |
| `sensor.person_profile_<name>` | One per person. State is a short line like "Alex: home, battery 82%". Attributes hold location, trackers, battery, related entities and AI results. |
| `sensor.person_profiles` | State is the number of people. The `profiles` attribute lists one summary per person. |

## How entities are linked to a person

1. The person's device trackers.
2. Every entity on the same device as those trackers.
3. Entities whose id or name contains the person's name (can be turned off).
4. Anything you add by hand in `person_extras`.

## Quick start

1. Install and start the add-on.
2. (Optional) set `ai_task_entity` to turn on AI summaries.
3. Check Developer Tools > States for `sensor.person_profile_`.

Read a value in a template:

```jinja
{{ state_attr('sensor.person_profile_alex', 'ai_summary') }}
{{ state_attr('sensor.person_profile_alex', 'battery') }}
```

See [DOCS.md](DOCS.md) for every option, events and examples.
