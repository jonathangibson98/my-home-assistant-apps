# Changelog

## 1.3.0

- **Games can be tagged to people** now, just like shows and movies. Pick who is tracking a game when you add it, or tap a name on its card.
- New per-person games sensor: `sensor.release_tracker_<name>_upcoming_games`. The main games sensor has a `by_person` attribute.
- New **People** card in Settings. Add one person at a time, rename them (their tags follow), or remove them (their tags and sensors go too).
- **Settings are organized into cards**: People, Movies & TV, Games, Updates, Home Assistant (MQTT), and Backup. Each has its own Save button and a status badge.
- New **Backup** card. Save your list, tags, and settings into a folder you choose in the share folder, on demand or daily or weekly. Restore from any saved backup. API keys are left out unless you turn them on.
- Saving one settings card no longer refreshes everything or reconnects MQTT unless it needs to.

## 1.2.0

- Added **video games and DLC**. Pick the **Games & DLC** switch on the Add tab and search by name.
- Track a game and its DLC and expansions show up automatically under it. Track a DLC directly if you only care about that.
- Games get **one** sensor: `sensor.release_tracker_upcoming_games`. No per-person game sensors, and games never touch the TV and movie sensors.
- Games data comes from IGDB (free). You need a free Twitch Client ID and Secret in Settings.
- Dates that are only a month or a year show as "expected" instead of a fake exact date.

## 1.1.0

- Added **people**. Tag each show or movie with who cares about it (you, MJ, anybody you add in Settings).
- Every person gets their own sensors: `sensor.release_tracker_<name>_upcoming` and `binary_sensor.release_tracker_<name>_releasing_today`.
- The main "Releasing Today" sensor now has a `by_person` attribute.
- Tap a name on any tracked card to change who it belongs to.
- Added icon, logo, and documentation.

## 1.0.0

- First release.
- Search TMDB and track any TV show or movie.
- TV: next episode or season premiere. Movies: theater, digital, and physical dates for your region.
- Publishes sensors to Home Assistant over MQTT with auto-discovery.
- Sidebar page for adding, removing, and refreshing.
