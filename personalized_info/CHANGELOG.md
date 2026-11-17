# Changelog

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
