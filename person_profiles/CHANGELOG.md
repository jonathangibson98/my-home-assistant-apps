# Changelog

## 0.2.0

- New web page in the sidebar: pick a person and fill in everything about them. Sections: About, Contact, Work and school, Health, Daily routine, Likes, Sizes and gifts, Vehicles, Important dates, Family friends and pets, Memberships, Notes and your own custom fields.
- Each section has its own switches: show it on the sensor, and share it with the AI. Contact, Health and Memberships start switched off.
- Worked out for you: age, zodiac sign, days until the birthday, and countdowns for important dates, family birthdays, vehicle due dates, renewals and checkups.
- Link any entity to a person from the page (a work hours sensor, a fitness tracker…), give it a label, or hide ones that were found automatically.
- The profile sensor gets `profile`, `age`, `zodiac`, `days_until_birthday`, `upcoming_dates`, `dates_next_30_days` and `profile_complete_percent` attributes. The AI now reads what you typed first, then the live entity data.
- Your data is saved in the add-on's own storage and included in add-on backups.

## 0.1.5

- Removed personal names, places and home-specific entity IDs from the defaults, examples and docs, so new installs start clean.

## 0.1.4

- Fix: Home Assistant event handlers run as tracked background tasks so they cannot be garbage-collected before they finish.
- Removed an unused variable.
- Versions 0.1.2 and 0.1.3 were maintenance releases that were not recorded here.

## 0.1.1
- Fix Docker build failing with an empty BUILD_FROM base image.
- Add icon, logo, README, DOCS and option translations.

## 0.1.0
- First version: per-person profile sensors, optional AI summaries, ask and refresh events.
