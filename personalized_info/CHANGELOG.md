# Changelog

## 0.4.0

- **Linked to your other add-ons.** Each person has a **Home Assistant** section: their person, phone, phone notifications, asleep (Sleep Tracker), at work and work hours (Work Hours Tracker), game console (PS5 Status), calendar and location sensor. **Find automatically** fills them in from the names those add-ons and the phone app use.
- **What everyone is doing right now.** With entities linked, the info sensor has a `now` block on each person, a `status` attribute and a `status_text` line per person (for example "home · asleep since 11:42 PM · playing NHL 26 · phone 64%"). `core_text` and `household_text` start each person with it, so AI announcements, facts and Voice Chat know. It's checked every minute and only republished when something changed. The People tab shows it next to each name.
- **Birthdays.** A `birthday` field (1998-05-06, 05-06, 5/6/1998 or May 6) gives `birthdays` (who, date, days until, age they're turning), `birthdays_today` and `birthdays_text` ("MJ has a birthday tomorrow...") on the info sensor, and a line at the top of the People tab.
- **Quick add** buttons for fields the other add-ons and AI prompts can use: birthday, nickname, say name as (for speech), pronouns, favorite teams, games they play, PSN ID, shows and movies, work schedule, usual bedtime and wake time.
- Places have a **zone** field (with a picker) so they line up with the zones Work Hours, Location Hub and Zone Creator use.
- Blank fields on people stay out of the sensor, like they already did for places.
- Fix: a hand-edited date without quotes (`birthday: 1998-05-06`) no longer stops the page from loading.

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
