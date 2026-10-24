# Changelog

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
