# Changelog

## 0.10.1 - 2026-11-26

- **Works with Work Hours' single sensor per person.** Link just the **Work hours** role (`sensor.<name>_hours`) and the info sensor now also knows whether they are at work, whether today is a day off, their next day off, their weekly schedule (`work_schedule`), today's shift, the next shift, and this week's and this pay period's hours (`work_*`), all read from that one sensor's attributes. The separate "At work" and "Day off" links still work if you use the older sensors.

## 0.10.0 - 2026-11-26

- **Day off (Work Hours).** A new **Day off** link for each person. Link Work Hours' `binary_sensor.<name>_day_off` (**Find automatically** finds it) and the info sensor says when someone is off today (`off today (Thanksgiving)`), what their next day off is, and lists who is off today in `off_today` / `off_today_text`.
- **More entities, for each person.** Under a person's Home Assistant section there is now **More entities**: link anything else (heart rate, steps, a car, a smart lock, a health sensor, a helper) with an optional label and extra attributes. **Find more** suggests entities named after them and the phone app's other sensors. The values go in the info sensor (`now.extra`) and, when "Say it" is ticked, in their one-line status. The phone's charging, activity, Wi-Fi and steps are picked up on their own.
- **House entities.** A new panel at the top links things about the house itself (weather, alarm, house mode, garage door, locks, energy). They appear in the info sensor as `house` (values) and `house_text` (one line each), so an AI Task knows what is going on at home.
- Every entity type can be picked now (lights, climate, locks, covers, helpers, todo lists, vacuums and more), not only sensors.

## 0.9.0 - 2026-11-17

- **🎲 Shuffle sensors** (replace the `interests_shuffle` and `artist_shuffle` AppDaemon apps):
  - **Random interest** (`sensor.random_interest`): every few minutes, a random hobby, game, show, team… (fields you pick) from someone who's home, with their `name`. A **wildcard** can sometimes pick from a helper's options instead (for example `input_select.fact_topics`).
  - **Random artist** (`sensor.random_artist`): a random artist from the music of the people who are home (plus the shared list), with `name` and `genres`. Picks again when someone gets home.
  - "Home" comes from each person's linked person entity, or from a locations sensor with one attribute per person. Leave out pets or guests. **Shuffle now** buttons.

## 0.8.1 - 2026-11-17

- **✨ Default AI** at the top of the page: pick the AI Task every add-on uses when its own `ai_task_entity` is empty (Personalized Info, Creator, Pi Health, Photo Hub, Sleep Tracker, Work Hours, Team Tracker, Release Tracker, Mobile Files, iCloud Lite). It's also a Home Assistant entity, `select.default_ai_task` (or `sensor.default_ai_task` without MQTT), so a dashboard or automation can change it.

## 0.8.0 - 2026-11-17

- **AI help**, using a Home Assistant AI Task entity (`ai_task_entity`, empty picks one). It works on what's on the page, saved or not, and only adds something when you tap it:
  - **Suggest fields** for a person (and for a place): useful fields they don't have yet, preferring names other people already use so everyone matches. Hover a suggestion for why.
  - **Fill from notes**: paste or type anything about someone and it becomes fields. Untick anything wrong before adding.
  - **Tidy fields**: finds duplicate or unclear fields and suggests merges, renames and removals.
  - **Gift ideas** from what's saved about someone.
  - New **Ask** tab: questions about everyone ("whose birthday is next?", "what info is missing for the voice assistant?").

## 0.7.2 - 2026-11-17

- **Easier to read over wallpapers.** The page checks how bright the wallpaper is and tints behind the text just enough to keep it readable: bright wallpapers get more, dark ones barely any.

## 0.7.1 - 2026-11-17

- Uses the shared **add-on wallpaper** you pick in Photo Hub (new *Add-on wallpaper* tab). This add-on's own Wallpaper option still wins when set.

## 0.7.0 - 2026-11-16

- **Pick the web UI wallpaper.** New **Wallpaper** option on the Configuration tab. Leave it empty to use your Home Assistant theme's wallpaper, enter `none` for no wallpaper, or point it at your own image: drop it in `/config/www` and enter the file name (e.g. `wallpaper.jpg`), `/local/wallpaper.jpg`, or a full `https://` link.

## 0.6.0 - 2026-11-16

- **Follows your Home Assistant theme.** The web UI now uses the colors of whatever theme Home Assistant is showing, light or dark, and changes live when you switch. Themes with a dashboard wallpaper and frosted-glass cards (like Apple / Liquid Glass themes) carry over too: wallpaper behind, see-through blurred cards, matching corners. Opened outside Home Assistant it keeps its own look.

## 0.5.2

- Removed personal names, places and home-specific entity IDs from the defaults, examples and docs, so new installs start clean.

## 0.5.1

- **No more duplicate fields.** When something better covers a field, it's hidden on the People tab and left out of the sensor, with a **Remove them** button to clear it out of the file:
  - `home_location` (and home, address, lives in...) when the person's **home** place has a zone or an address
  - work location fields (work_location, workplace, works_at...) when their **work** place has a zone or an address. A job title like `occupation` stays
  - `age` when the birthday has a year: the sensor now gives an `age` worked out from it, so it never goes stale
  - a second birthday field (for example both `birthday` and `dob`)
- Removing a home location whose home place has no address yet moves it into that place's address, so nothing is lost.
- **Birthdays read `dob`** (and `date_of_birth`, `birth_date`), not only `birthday`, so the countdown and birthday attributes work with existing people. The Birthday quick-add button is hidden when they already have one.

## 0.5.0

- **Places link to Home Assistant zones.** Every place (old ones too) has a **Home Assistant zone** picker at the top of its card, and **Find matching zone** picks the zone with the same name (or `zone.home` for the place your household calls home).
- When someone linked on the People tab is in a place's zone, their status names the place and what it is to them: "at Office (work)" instead of the zone's own name. Their `now` gets `place`, `place_key` and `place_role`, and that place is marked `here_now` in their places.
- Each place in the sensor gets `people_here`, and there's a new `places_text` attribute ("Office (zone.office): Alex here now"). The Places tab shows who's at each place.

## 0.4.0

- **Linked to your other add-ons.** Each person has a **Home Assistant** section: their person, phone, phone notifications, asleep (Sleep Tracker), at work and work hours (Work Hours Tracker), game console (PS5 Status), calendar and location sensor. **Find automatically** fills them in from the names those add-ons and the phone app use.
- **What everyone is doing right now.** With entities linked, the info sensor has a `now` block on each person, a `status` attribute and a `status_text` line per person (for example "home · asleep since 11:42 PM · playing NHL 26 · phone 64%"). `core_text` and `household_text` start each person with it, so AI announcements, facts and Voice Chat know. It's checked every minute and only republished when something changed. The People tab shows it next to each name.
- **Birthdays.** A `birthday` field (2000-01-15, 01-15, 1/15/2000 or Jan 15) gives `birthdays` (who, date, days until, age they're turning), `birthdays_today` and `birthdays_text` ("Sam has a birthday tomorrow...") on the info sensor, and a line at the top of the People tab.
- **Quick add** buttons for fields the other add-ons and AI prompts can use: birthday, nickname, say name as (for speech), pronouns, favorite teams, games they play, PSN ID, shows and movies, work schedule, usual bedtime and wake time.
- Places have a **zone** field (with a picker) so they line up with the zones Work Hours, Location Hub and Zone Creator use.
- Blank fields on people stay out of the sensor, like they already did for places.
- Fix: a hand-edited date without quotes (`birthday: 2000-01-15`) no longer stops the page from loading.

## 0.3.7

- Fix: the periodic MQTT republish loop is kept referenced so it cannot be garbage-collected.
- Added option labels (`translations/en.yaml`) so the Configuration tab shows names and descriptions.

## 0.3.6
- Changed Backup files it keeps to 5 not 20

## 0.3.5
- Bug Fixes

## 0.3.4
- Made linking for places and person so info is linked.

## 0.3.3
- Updated how the music section works.

## 0.1.2
- Added icon, logo, README, and docs.

## 0.1.1
- Renamed from Household Info to Personalized Info.

## 0.1.0
- Initial release.
