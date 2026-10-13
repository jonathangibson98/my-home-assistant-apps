# Team Tracker Lite

A Home Assistant add-on that gives you **one** live sports sensor, and lets you choose which team feeds it from a menu in the sidebar. No YAML, no pile of per-team sensors eating RAM.

It pulls scores and schedules from ESPN's public API for the single team you're tracking and publishes them over MQTT. State values (`PRE`, `IN`, `POST`, `NOT_FOUND`) and attribute names (`team_abbr`, `team_score`, `opponent_logo`, ...) match the [Team Tracker integration](https://github.com/vasqued2/ha-teamtracker), so cards built for it keep working.

## Features
- One sensor (`sensor.team_tracker` by default, rename it in the panel)
- Pick a league, then a team, from dropdowns, with a search box for long lists
- Save as many teams as you like and switch the tracked one with a single tap
- Refreshes slowly when nothing is on and quickly during a game, and you set both speeds in the panel
- Optional `select` entity so dashboards and automations can switch teams
- Settings survive restarts and reinstalls of the add-on image
- Log level you can turn up when something misbehaves

## Install
1. Copy the `team_tracker_lite` folder into `/addons/` on your Home Assistant.
2. Settings > Add-ons > Add-on Store > the three dots > **Check for updates**.
3. Open **Team Tracker Lite** under Local add-ons and install it.
4. On the **Configuration** tab, enter your MQTT broker (host, port, user, password). Leave `mqtt_host` blank only if you use the Mosquitto broker add-on.
5. Start it, open **Team Tracker** in the sidebar, add a team, and tap **Track**.

## Where your settings are saved
Everything you set in the panel (saved teams, the tracked team, sensor name, refresh speeds) is written to one file in the add-on's config folder:

```
/addon_configs/<repository id>_team_tracker_lite/data/settings.json
```

On a typical local install the folder is `/addon_configs/e707995f_team_tracker_lite/data/`. You can read it with the Samba share or the File editor add-on, copy it to back it up, or edit it (restart the add-on afterwards). If that folder can't be written to, the add-on logs a warning and falls back to its private `/data` folder.

## Configuration tab options
| Option | Default | What it does |
| --- | --- | --- |
| `mqtt_host` | blank | Your MQTT broker. Blank means "use the Mosquitto add-on". |
| `mqtt_port` | 1883 | Broker port. |
| `mqtt_username` / `mqtt_password` | blank | Broker login. |
| `publish_team_selector` | off | Also create a `select` entity that switches the tracked team. |
| `log_level` | info | `debug`, `info`, `warning` or `error`. |

Refresh speeds are not here. They live in the panel under **How often to refresh**.

## Logging
Open the add-on's **Log** tab.

| Level | You will see |
| --- | --- |
| `error` | Problems that stop something working (no MQTT broker, a failed poll). |
| `warning` | Things that recovered or degraded (MQTT dropped, live scoreboard fell back to schedule data). |
| `info` | Startup details, MQTT connection, teams added/removed/tracked, and state changes (PRE to IN to POST). The default. |
| `debug` | Everything above plus every ESPN request, every refresh result, the next wait time, and MQTT traffic. Noisy, so switch it back when you're done. |

## Troubleshooting
- **Build fails with "network is unreachable" for registry-1.docker.io.** The host can't reach Docker Hub, often an IPv6 problem. Retry, or disable IPv6 under Settings > System > Network.
- **The sensor never appears.** Check the footer of the panel for "Connected to MQTT". If it says not connected, fix the broker settings and restart. Set `log_level` to `debug` for details.
- **Team list or scores are empty.** Set `log_level` to `debug` and look for the ESPN URL being requested and its error.
- **State is `NOT_FOUND`.** ESPN has no scheduled game for that team right now (offseason, or the schedule isn't published yet).

## Limits
Team sports only: NFL, NBA, MLB, NHL, WNBA, college football and basketball, MLS, NWSL and the major soccer leagues. Golf, tennis, racing, UFC and custom API paths are not supported.

## Credits
Inspired by [vasqued2/ha-teamtracker](https://github.com/vasqued2/ha-teamtracker) (itself a fork of zacs/ha-nfl). This add-on is a separate, much smaller implementation and uses ESPN's unofficial public API, which can change without notice.
