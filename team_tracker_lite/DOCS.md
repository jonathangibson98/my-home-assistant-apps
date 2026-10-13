# Team Tracker Lite

One sensor. Any team. Picked from a menu in the sidebar panel.

## Setup
1. On the **Configuration** tab, enter your MQTT broker (host, port, user, password). Leave `mqtt_host` blank only if you use the Mosquitto broker add-on.
2. Start the add-on and open **Team Tracker** in the sidebar.
3. Pick a league, pick a team, tap **Add team**. Repeat for any teams you want to switch between.
4. Tap **Track** on the team you want the sensor to show.

The sensor is `sensor.team_tracker` (rename it in the panel). States are `PRE`, `IN`, `POST` and `NOT_FOUND`.

## Your settings
Saved teams, the tracked team, the sensor name and the refresh speeds are saved in `/addon_configs/<id>_team_tracker_lite/data/settings.json`.

## Options
- `publish_team_selector`: also creates a `select` entity so automations and dashboards can switch teams.
- `log_level`: `debug`, `info`, `warning` or `error`. Use `debug` when troubleshooting.

Refresh speeds (idle and during a game) are set in the panel, not here.

## Not supported
Golf, tennis, racing, UFC and custom API paths. Team sports only.
