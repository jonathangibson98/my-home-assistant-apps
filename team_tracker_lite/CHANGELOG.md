# Changelog

## 0.3.1
- Fix: picking a live game could snap the Home Assistant team dropdown back to the previously tracked team. The add-on now re-sends the dropdown's current choice a couple of seconds after any change, and on every refresh.

## 0.3.0
- Calendar: every game for every saved team as an `.ics` feed on port 8100, for Home Assistant's Remote Calendar integration. Rebuilt daily at a time you choose, rebuilt when you add or remove a team, with an "Update now" button. Refreshes the HA calendar entity after each rebuild.
- Live game slot: pick a sport, pick a game in progress, track its score. Not included in the calendar.
- The select entity (if enabled) now includes the live game.
- Needs `homeassistant_api` access (to refresh the calendar entity and read your time zone).

## 0.2.0
- Settings now saved in the add-on config folder (`addon_configs/.../data/settings.json`).
- Refresh speeds (idle and live) moved from the Configuration tab into the panel.
- New `log_level` option (debug, info, warning, error) and much more useful logging.
- Added icon, logo, README and docs.

## 0.1.0
- First version: one MQTT sensor, team menus in the panel, saved teams, optional team selector entity.
