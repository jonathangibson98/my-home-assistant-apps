# Changelog

## 1.6.0

Tidy-up of the person page.

- **Birthday** is a real date picker, with a "I don't know the year" box that switches it to month and day. It reads whatever you had saved (`dob`, `May 6, 1998`, `05-06`, `5/6/1998`) and saves it back in a format the add-on understands. If a saved value can't be read it tells you.
- **Home**: pick **Type an address** or **Link a Home Assistant zone**. A zone is linked through a home place (an existing place with that zone is reused, otherwise one is made for you), so "at home" works in their status.
- **Home Assistant links moved into the sections**: person and location sensor in About, phone and phone notifications in Contact, at work, work hours and day off in Work, asleep in Routine, game console in Likes, calendar in Dates, and other entities in Notes. "Find their Home Assistant entities automatically" is in About. The separate Home Assistant card is gone.
- **Your own fields** only lists fields with no spot in the sections, so nothing shows up twice. Each field is in its own box, the name has its own box at the top of the page, and `nickname_1`, `nickname_2` hide once the nickname is filled in (with a Remove button).
- Removed **Relationships between people** from the bottom of the People tab. Each person's own Relationships card is still on their page.
- **Zone icons in the picture picker**: a new **Zone icons** section lists your Home Assistant zones with the icon you set on each one. Tap one to use it as the picture for a person or place (a place's own zone is listed first). Zones with no icon (or a non-Material-Design one) get a map pin. The icon is saved as a small round picture in `www/personalized_info`, so it also works as the `entity_picture`. It is fetched from the Material Design Icons set the first time and cached, so the add-on needs internet for an icon it has not used before. If you change a zone's icon later, pick it again to refresh.

## 1.5.0

Link people to each other, with nobody as the "main" person.

- New **Relationships** card on every person, and **Relationships between people** on the People tab. Pick any two people and how they are linked: dating, engaged, married, exes, best friends, friends, roommates, coworkers, neighbors, siblings, cousins, family, parent / child, owner / pet, or doesn't like. Add a date they started and a note.
- A link belongs to both people, so it shows on both pages and you can add or remove it from either one. Directional ones (parent / child, owner / pet) read correctly from each side.
- First run builds the links from what you already saved: `girlfriend` / `boyfriend` / `partner` (with "together since" as the date), `friends` lists, "Jon and MJ's dog", and "MJ's sister". They are saved in `relationships.yaml`.
- Once a person's partner or friends are all linked, their old `girlfriend` / `friends` fields show as "covered by the Relationships card" with a button to remove them. Until then they stay as they were.
- The Family section no longer has Partner and Friends fields (the card replaces them). Relatives and pets with details are still there.
- **Picture picker** for people and places, like the one on the Location Hub card: a sheet with Upload, paste a link, Automatic, your Home Assistant people's pictures, and the images in your `www` folder. Tap one to use it.
- `sensor.person_profile_<name>` has `relationships` (for example "Dating MJ since 2023-05-19") and `relationship_links`. The Ask tab and AI prompts see the links too.

## 1.4.0

Fills your profile sections from what you already saved, with no AI needed.

- New: **Fill from what is saved (no AI)** on every person, and **Fill everyone from what is saved (no AI)** on the People tab. It files first and last name, employer and work address (from their work place), home address (from their home place), a yearly "Together with ..." date (from "together since ..." next to the partner), and their favorite artists. Nothing is guessed and nothing already filled in is overwritten.
- New: people are filled this way automatically, once each, the first time the add-on sees them. A field you clear later stays cleared.
- Fixed: the Birthday field only looked for `birthday`, so anyone saved with `dob` showed it empty. It now reads `dob`, `date_of_birth`, `birth_date` and `birthdate` too. Same for `nicknames` and `nick`, and `nickname_1`, `nickname_2` are joined into one nickname.
- Fixed: when the AI errors out (busy, out of credit, bad answer), the AI fill now still returns what could be filled without it and tells you what the AI said, instead of failing with nothing.
- The preview only lists what would really be added, not things that are already there.

## 1.3.0

Your older fields and the profile sections are now the same thing, so there is nothing to move.

- Sections show and edit your existing fields in place: job (`occupation`), hobbies, friends, partner (`girlfriend` / `boyfriend`...), car, notes, wake and bed time, where they live (`home_location`), role or relationship, sports teams, games, PSN ID, breed, sex, traits and how they get around. They are saved under the field name you already use, so the info sensor, other add-ons and AI prompts see exactly what they saw before. Fields marked ↔ in a section are these.
- Anything an earlier version stored in a section for one of those fields moves to the person's own field automatically.
- The AI fill reads and writes these same fields, so it adds to what you have instead of creating a second copy.
- `sensor.person_profile_<name>` now has a `details` attribute with all their own fields, so one sensor has everything about a person.
- Removed the "Move old fields into sections" buttons: no longer needed.

## 1.2.0

- **✨ Fill the sections with AI**: your AI Task reads everything saved about a person (any field names, any wording) and files it into the profile sections: work, likes, family and friends, vehicles, important dates, notes and more. It also adds teams and games to their own fields. You see exactly what it would add first. It only fills empty spots or adds to lists, never overwrites, and nothing is saved until you press Save changes.
- A **✨ Fill everyone's sections with AI** button at the bottom of the People tab does the whole household and friends one person at a time (with a Stop button). It keeps all your old fields.
- Optional per person: also remove the old fields the AI moved.
- The AI can only fill fields that exist in the form. Anything else it makes up is thrown away.

## 1.1.0

- Notable people (`other` > `notable_people`) are in the People grid too, with a picture and notes for each. Setting a picture turns that entry from a plain list into a name, notes and picture. Entries you don't touch stay as they were.
- **Move old fields into sections**: a tidy-up button (on each person, and for everyone at the bottom of the People tab) that moves older free-form fields into the matching profile section: occupation, girlfriend/boyfriend/partner, friends, hobbies, sports teams, car, role, notes and wake or bed time. You tick what to move and nothing is final until you Save. Moved fields leave Your own fields so nothing shows twice.

## 1.0.0

Personalized Info and Person Profiles are now one add-on. Everything you already saved here stays: the same files (`people.yaml`, `places.yaml`, `music.yaml` in `ai_memory`), the same sensors and the same settings are used.

- The People tab is now a grid of people with their picture, where they are right now and how much of their profile is filled in. Tap someone to open everything about them.
- Pictures: a person's Home Assistant picture shows by default. Add your own for anyone (household, friends and other notable people) from a photo or a link. They are saved in `www/personalized_info` so dashboards can use them (`entity_picture` on the sensors).
- Pictures for places and zones: each place can have one. It shows on the Places tab, and as a small badge on a person while they are at that place.
- Profile sections for every person: About, Contact, Work and school, Health, Daily routine, Likes, Sizes and gifts, Vehicles, Important dates, Family friends and pets, Memberships, Notes and custom fields. Contact, Health and Memberships start hidden from the sensors.
- Your own fields, Quick add, AI help, Places and Home Assistant links are all still on each person, as their own sections.
- Birthday, nickname, pronouns, favorite teams and games in the profile use the fields you already have, so nothing is entered twice.
- Worked out: age, zodiac sign, birthday countdown and countdowns for important dates, family birthdays, vehicle due dates, renewals and checkups.
- New sensor per person, `sensor.person_profile_<name>` (the same names Person Profiles used) with their profile, live status, picture, countdowns and an optional AI summary. `sensor.person_profiles` lists everyone. The info sensor also gets each person's `profile`, `zodiac` and `coming_up`.
- The separate Person Profiles add-on is retired: uninstall it after updating. Its `person_profile_ask` and `person_profile_refresh` events are gone; use the Ask tab or the AI summary button instead.

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
