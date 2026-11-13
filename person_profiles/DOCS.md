# Person Profiles

Creates `sensor.person_profile_<name>` for each person, plus `sensor.person_profiles` (all summaries).

Entities are linked to a person by: their device trackers, every entity on the same device as a tracker, name matching, and your manual `person_extras`.

## AI
Set `ai_task_entity` (preferred) or `conversation_agent`. Summary runs every `ai_interval_minutes` (0 = only on request).

## Events
- `person_profile_refresh`  data: `person` (optional), `ai` (true = run AI now)
- `person_profile_ask`      data: `person`, `question`, `request_id` (optional)
- `person_profile_answer`   fired back with `person`, `question`, `answer`, `request_id`
