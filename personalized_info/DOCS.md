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
| Person | `person.alex` | Home Assistant |
| Phone | `device_tracker.jons_iphone` | the Companion app (its `_battery_level` sensor is used too) |
| Phone notifications | `notify.mobile_app_jons_iphone` | the Companion app |
| Asleep | `binary_sensor.alex_asleep` | Sleep Tracker |
| At work / Work hours | `binary_sensor.alex_at_work` / `sensor.alex_hours` | Work Hours Tracker |
| Game console | `media_player.ps5_512` | PS5 Status |
| Calendar | `calendar.alex` | any calendar |
| Location sensor | your location sensor | Location Hub |

The info sensor then has, for each linked person:

- `now`: location, asleep (and since when), at work, work hours, what they're playing, calendar event, phone battery, and a one-line `text`
- `status` (everyone's `now`), `status_text` (one line per person) and `entities` (what each person is linked to)

It's checked every minute and only sent to Home Assistant when something changed.

## Birthdays

Add **Birthday** to a person (2000-01-15, or 01-15 without the year). The info sensor gets `birthdays` (sorted by days until, with the age they're turning when the year is known), `birthdays_today` and `birthdays_text`. Use them in AI announcements, for example a Birthday Announce automation that runs when `birthdays_today` isn't empty.

## Quick add fields

The **Quick add** buttons add fields other add-ons and AI prompts can use: nickname, say name as (how a voice should say it), pronouns, favorite teams, games they play, PSN ID, shows and movies, work schedule, usual bedtime and wake time. Blank fields stay out of the sensor.

## Places and zones

Open a place on the **Places** tab and set its **Home Assistant zone** (or tap **Find matching zone**). Then, for anyone linked to their `person` on the People tab:

- their status says where they are by the place's name and what it is to them, for example **at Office (work)** or **at Our House (home)**
- the place lists who's there (`people_here` on the place, and `places_text` on the info sensor)

Home Assistant reports a person in a zone by the zone's name, and `home` for `zone.home`, so the zone has to exist in Home Assistant (make one with Zone Creator if it doesn't).

## Fields that are covered elsewhere

Some fields repeat what a linked place or the birthday already says. Those are hidden on the People tab (listed under **Covered elsewhere**) and left out of the sensor:

| Field | Covered when |
|---|---|
| `home_location`, `home`, `address`, `lives_in`... | their **home** place has a zone or an address |
| `work_location`, `workplace`, `works_at`... | their **work** place has a zone or an address |
| `age` | the birthday has a year (the sensor works the age out) |
| a second birthday field | they already have `dob` or `birthday` |

**Remove them** deletes them from the file. A home location the home place doesn't have yet becomes that place's address.

## AI help

Each person (and place) has an **✨ AI help** row. It uses a Home Assistant AI Task entity: set `ai_task_entity`, or leave it empty to use the first one. Nothing changes until you tap something, and it all still needs **Save changes**.

- **Suggest fields**: fields worth adding, matched to the names other people use.
- **Fill from notes**: free text in, fields out. Untick anything wrong, then **Add**.
- **Tidy fields**: merge duplicates, rename unclear fields, drop empty ones.
- **Gift ideas** for someone, from what's saved.
- **Ask** tab: ask anything about the people, places and music here.

What's on the page is sent to your AI provider when you use these.
