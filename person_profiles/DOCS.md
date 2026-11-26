# Person Profiles: Documentation

## The web page

Open **Person Profiles** in the sidebar, pick a person and fill in whatever you know. Press **Save** and their sensor updates right away.

Sections: About, Contact, Work and school, Health, Daily routine, Likes and preferences, Sizes and gifts, Vehicles, Important dates, Family friends and pets, Memberships and subscriptions, Notes and your own custom fields.

Every section has two switches:

- **Show on the sensor**: puts it in the `profile` attribute. Contact, Health and Memberships start off, because anything in a sensor can be read by anyone with access to Home Assistant.
- **Share with the AI**: the AI reads it when it builds summaries and answers questions.

Worked out for you: age, zodiac sign, days until the birthday, and countdowns for important dates, family birthdays, vehicle registration, insurance and service dates, renewals and checkups.

**Linked entities**: search any entity and link it to the person (their Work Hours sensor, a fitness tracker, a phone battery). Linked entities always appear in the sensor and the AI data. Entities found automatically can be hidden.

Please do not store passwords, card numbers or ID numbers. There are no fields for them on purpose. Your data is saved in the add-on's own storage (`/data/profiles.json`) and is included in add-on backups.

New sensor attributes: `profile`, `age`, `zodiac`, `next_birthday`, `days_until_birthday`, `birthday_today`, `upcoming_dates`, `dates_next_30_days`, `profile_complete_percent`.

## Sensors

### `sensor.person_profile_<name>`
State: a short rule-based line, for example `Alex: home, battery 82%`.

Attributes:

| Attribute | Meaning |
| --- | --- |
| `person_entity`, `name`, `user_id` | Who this profile is for |
| `location`, `latitude`, `longitude`, `gps_accuracy`, `source` | Copied from the person entity |
| `battery` | First battery sensor found among related entities |
| `trackers` | Each device tracker and its state |
| `entity_count` | How many related entities were found |
| `entities` | Related entities and their states (limited by `max_entities_in_sensor`) |
| `ai_summary`, `ai_facts`, `ai_routine`, `ai_updated` | Latest AI results |
| `last_question`, `last_answer`, `last_answer_time` | Latest answer from `person_profile_ask` |
| `last_updated` | When the add-on last wrote the sensor |

### `sensor.person_profiles`
State is the number of people. The `profiles` attribute maps each person to their AI summary (or the rule-based line if there is none yet).

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `people` | empty | Person entities to include. Empty means all. |
| `update_interval_seconds` | 60 | Refresh rate for the sensors. |
| `name_matching` | true | Link entities by name. |
| `include_unavailable` | false | Keep unavailable or unknown entities. |
| `max_entities_in_sensor` | 60 | Entities listed in the sensor attributes. |
| `max_entities_for_ai` | 150 | Entities sent to the AI. |
| `exclude_domains` | update, button, scene, event, tts, stt | Domains to ignore. |
| `exclude_entity_patterns` | empty | Glob patterns to ignore, such as `sensor.*_uptime`. |
| `person_extras` | empty | Entities to always link to a person. |
| `ai_task_entity` | empty | ai_task entity for AI (preferred). |
| `conversation_agent` | empty | Used only if no AI Task entity is set. |
| `ai_interval_minutes` | 60 | AI summary rate. 0 means only on request. |
| `ai_extra_prompt` | empty | Extra instructions added to every AI request. |
| `log_level` | info | Add-on log detail. |

Example:

```yaml
people:
  - person.alex
ai_task_entity: ai_task.my_assistant
ai_interval_minutes: 60
exclude_entity_patterns:
  - sensor.*_uptime
person_extras:
  - person: person.alex
    entities:
      - sensor.alex_work_laptop
```

## Events

Fire these from Developer Tools > Events, an automation or a script.

### `person_profile_refresh`
Refresh now. Data (all optional): `person` to limit to one person, `ai: true` to run AI too.

### `person_profile_ask`
Ask the AI a question about a person.

```yaml
event: person_profile_ask
event_data:
  person: person.alex
  question: "Is he usually home by 6pm?"
  request_id: abc123
```

The answer is saved in `last_answer` and fired back as `person_profile_answer` with `person`, `question`, `answer` and `request_id`.

Automation trigger example:

```yaml
trigger:
  - platform: event
    event_type: person_profile_answer
    event_data:
      request_id: abc123
action:
  - service: notify.notify
    data:
      message: "{{ trigger.event.data.answer }}"
```

## Notes

- Sensors are written through the Home Assistant API, so they have no unique id and cannot be edited in the UI. They return within one update cycle after HA restarts.
- The `entities` attribute can be large. Add `sensor.person_profile_*` to your recorder excludes.
- The AI only sees the entity data. It is told not to invent anything, but always check important answers.
- Without an AI entity everything still works. Only the `ai_*` attributes stay empty.

## Troubleshooting

- **No sensors:** check the add-on log, and make sure you have at least one `person.` entity.
- **Empty entity list:** a person with no device trackers needs `name_matching` or `person_extras`.
- **AI fields empty:** check `ai_task_entity` is a real `ai_task.` entity, then fire `person_profile_refresh` with `ai: true` and read the log.
