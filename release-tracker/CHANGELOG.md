# Changelog

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
