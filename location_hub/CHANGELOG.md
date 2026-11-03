# Changelog

## 1.0.0
- Combined **Location Tracker** (0.10.0) and **Arrival Alerts** (1.0.4) into one add-on with one web UI.
- One Python process, one ingress port. Every feature from both add-ons is kept.
- New UI: **Location** (Switches, Devices, Sensor trackers, Dashboard card) and **Alerts** (Places, People & sensors, Notifications, Activity), one Save bar for everything.
- Alerts now use this add-on's own location sensor as the "Our Locations" context when the Locations sensor field is left blank.
- New optional `unique_id` option, so an existing location sensor can keep its identity when moving over from the old Location Tracker add-on.
