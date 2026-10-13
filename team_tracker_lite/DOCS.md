# Team Tracker Lite

One sensor. Any team. Picked from a menu in the sidebar panel.

## Setup
1. In the add-on **Configuration** tab, fill in your MQTT broker (host, port, user, password). Leave `mqtt_host` blank only if you use the Mosquitto broker add-on.
2. Start the add-on and open **Team Tracker** in the sidebar.
3. Pick a league, pick a team, tap **Add team**. Repeat for any teams you want to switch between.
4. Tap **Track** on the team you want the sensor to show.

The sensor is `sensor.team_tracker` (rename it in the panel). States: `PRE`, `IN`, `POST`, `NOT_FOUND`. Attribute names match the Team Tracker integration (`team_abbr`, `team_score`, `opponent_logo`, ...).

## Options
- `idle_minutes`: how often to check when nothing is live (default 10).
- `live_seconds`: how often to refresh during a game (default 15).
- `publish_team_selector`: also creates a `select` entity so automations and dashboards can switch teams.

## Not supported (yet)
Golf, tennis, racing, UFC, and custom API paths. This is team sports only.
