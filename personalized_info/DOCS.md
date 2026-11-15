# Personalized Info: Documentation

## Where the data lives

| What | Path |
|---|---|
| Main data file | `/homeassistant/ai_memory/people.yaml` |
| Backups (last 5) | `/homeassistant/ai_memory/backups/` |

## Using the UI

- **Save** writes the file. Nothing is saved until you press it. The bottom bar says "Unsaved changes" when you have edits pending.
- **+ field** adds a text value, **+ list** adds a one-per-line list, **+ group** adds a nested section.
- **✕** deletes a field. **Delete person** removes the whole card.
- Music genres and artists are one entry per line.

## Notes

- If two copies of the app run at once, the last save wins.
- The `homeassistant_config:rw` mapping is what lets the app read and write your config folder.

## Linking people to Home Assistant

Open a person and go to **Home Assistant** at the bottom of their card. Tap **Find automatically** (save first), or pick each entity yourself:

| Role | Usually | From |
|---|---|---|
| Person | `person.jon` | Home Assistant |
| Phone | `device_tracker.jons_iphone` | the Companion app (its `_battery_level` sensor is used too) |
| Phone notifications | `notify.mobile_app_jons_iphone` | the Companion app |
| Asleep | `binary_sensor.jon_asleep` | Sleep Tracker |
| At work / Work hours | `binary_sensor.jon_at_work` / `sensor.jon_hours` | Work Hours Tracker |
| Game console | `media_player.ps5_512` | PS5 Status |
| Calendar | `calendar.jon` | any calendar |
| Location sensor | your location sensor | Location Hub |

The info sensor then has, for each linked person:

- `now`: location, asleep (and since when), at work, work hours, what they're playing, calendar event, phone battery, and a one-line `text`
- `status` (everyone's `now`), `status_text` (one line per person) and `entities` (what each person is linked to)

It's checked every minute and only sent to Home Assistant when something changed.

## Birthdays

Add **Birthday** to a person (1998-05-06, or 05-06 without the year). The info sensor gets `birthdays` (sorted by days until, with the age they're turning when the year is known), `birthdays_today` and `birthdays_text`. Use them in AI announcements, for example a Birthday Announce automation that runs when `birthdays_today` isn't empty.

## Quick add fields

The **Quick add** buttons add fields other add-ons and AI prompts can use: nickname, say name as (how a voice should say it), pronouns, favorite teams, games they play, PSN ID, shows and movies, work schedule, usual bedtime and wake time. Blank fields stay out of the sensor.

