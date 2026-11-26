# Personalized Info: Documentation

## Where the data lives

| What | Path |
|---|---|
| Main data file | `/homeassistant/ai_memory/people.yaml` |
| Backups (last 5) | `/homeassistant/ai_memory/backups/` |

## People and profiles

The **People** tab shows everyone as a card: picture, where they are now, and how much of their profile is filled in. Tap a card to open that person. They have, from the top:

- a **picture** (add your own, or use a link; without one it shows their Home Assistant person picture) and a summary: age, sign, birthday countdown, what is coming up in the next 30 days, and an optional **AI summary**
- **profile sections**: About, Contact, Work and school, Health, Daily routine, Likes, Sizes and gifts, Vehicles, Important dates, Family friends and pets, Memberships, Notes and custom fields. Each has a **Show on the sensors** switch. Contact, Health and Memberships start off, because anything on a sensor can be read by anyone with Home Assistant access
- **Your own fields**, **AI help**, **Places** and **Home Assistant** links (see below)

Birthday, nickname, pronouns, favorite teams and games in the profile are the same fields as under Your own fields, so nothing is entered twice. Please don't store passwords, card numbers or ID numbers: there are no fields for them on purpose.

Profile sections are saved in `/homeassistant/ai_memory/profiles.yaml`. Pictures are saved in `/homeassistant/www/personalized_info/` and show at `/local/personalized_info/...` (if you have never had a `www` folder, restart Home Assistant once).

Each person also gets **`sensor.person_profile_<name>`** (state: what they are doing now) with `profile`, `age`, `zodiac`, `days_until_birthday`, `upcoming_dates`, `dates_next_30_days`, `entity_picture`, `ai_summary` and more, and **`sensor.person_profiles` lists everyone. Add `sensor.person_profile_*` to your recorder excludes: they can be large.

## Let the AI fill the sections

Open a person and use **✨ Fill the sections with AI**, or use **✨ Fill everyone's sections with AI** at the bottom of the People tab. Your AI Task (the `ai_task_entity` option, the Default AI in ⚙️ Settings, or the first AI Task it finds) reads everything saved about the person, whatever the field names are, and files it into the sections. It never overwrites something already filled in, only adds, and it reads and writes the same fields as above. Check the result, then press **Save changes**. Tick "also remove the old fields it moved" if you don't want the old copies. What is on the page is sent to your AI provider.

## Your own fields and the sections are the same data

Fields you added by hand over time (`occupation`, `hobbies`, `friends`, `girlfriend`, `car`, `notes`, `usual_wake_time`, `home_location`, `sports`, `games`, `psn_id`...) show up in the matching profile section, marked ↔, and editing them there edits the original field under the name you already use. Nothing is copied or moved, so everything that reads those fields (the info sensor, other add-ons, AI prompts) keeps working. Other fields stay under **Your own fields**.

## Notable people

People listed under `other` > `notable_people` get their own cards. Open one to add a picture, a name and notes.

## Pictures for places

Open a place on the **Places** tab and add a picture. It shows next to the place, and as a small badge on a person's card while they are at that place (the place needs its Home Assistant zone set).

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

## Default AI for all add-ons

**✨ Default AI** at the top of the page sets the AI Task entity every add-on uses when its own `ai_task_entity` option is empty: Personalized Info, Creator & AI Builder, Pi Health Monitor, Photo Hub, Sleep Tracker, Work Hours, Team Tracker Lite, Release Tracker, Mobile Files and iCloud Lite. **Automatic** uses the first AI Task Home Assistant has.

It's also an entity in Home Assistant, `select.default_ai_task` (`sensor.default_ai_task` without an MQTT broker), so you can switch it from a dashboard or an automation.

## AI help

Each person (and place) has an **✨ AI help** row. It uses a Home Assistant AI Task entity: set `ai_task_entity`, or leave it empty to use the first one. Nothing changes until you tap something, and it all still needs **Save changes**.

- **Suggest fields**: fields worth adding, matched to the names other people use.
- **Fill from notes**: free text in, fields out. Untick anything wrong, then **Add**.
- **Tidy fields**: merge duplicates, rename unclear fields, drop empty ones.
- **Gift ideas** for someone, from what's saved.
- **Ask** tab: ask anything about the people, places and music here.

What's on the page is sent to your AI provider when you use these.

## Shuffle sensors

**🎲 Shuffle sensors** at the top of the page make random picks for dashboards and announcements (they replace the `interests_shuffle` and `artist_shuffle` AppDaemon apps):

- **Random interest** (default `sensor.random_interest`): state = an item from the fields you list (hobbies, games, favorite teams…) of someone who's home; attributes `name`, `person`, `field`. With a **wildcard** entity (an input_select), it sometimes picks one of its options instead (`name: Wildcard`).
- **Random artist** (default `sensor.random_artist`): state = an artist from the music of the people who are home, plus the shared list; attributes `name`, `genres`. It picks again when someone gets home (checked every minute).

Who's home: each person's linked person entity (People tab → Home Assistant), or a **locations sensor** with one attribute per person (for example `alex: Home`), with the states that count as home. Leave out pets or guests by name.

Moving from AppDaemon: remove the two apps from `apps.yaml`, restart Home Assistant once so the old sensors are gone, then turn these on so they take the same entity IDs.
