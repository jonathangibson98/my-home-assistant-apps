# iCloud Lite

Tracks the Apple devices you pick, from as many iCloud accounts as you want, and publishes them to Home Assistant over MQTT. No dashboards, no stationary zones.

## Requirements
- The **Mosquitto broker** add-on (or any MQTT broker) plus the MQTT integration in Home Assistant.

## Use
1. Start the add-on and open **iCloud Lite** in the sidebar.
2. Add an Apple ID + password.
3. Type the 6-digit code Apple sends to your trusted device.
4. Tick the devices to track and set the update interval, then **Save**.
5. Repeat for any other Apple ID.

Each device shows up as a `device_tracker` plus a battery sensor. Home Assistant's own zones decide home/away.

## Options (only if you don't use the Mosquitto add-on)
`mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password`. Leave blank to auto-detect.

## Logging (Configuration tab)
- `log_level`: `debug`, `info` (default), `warning`, or `error`.
  - `info` shows logins, 2FA events, fast-mode on/off, devices added or removed, and MQTT discovery.
  - `debug` adds every poll, how close devices are to zones, and every MQTT state publish.
  - `warning` and `error` show only problems.
- `log_pyicloud`: turns on the Apple library's own debug output. Leave it off unless troubleshooting, because it can include sensitive request details. Don't paste those logs anywhere public.
- Passwords and 2FA codes are never written to the log. Accounts appear by tab name, not email.
- Restart the add-on after changing either option.

## Notes
- Each update asks Apple to actively locate your devices. The fresh fix lands on the next update.
- Passwords are stored in this add-on's private `/data` folder.
- A failed login is retried only every 30 minutes, so Apple doesn't lock the account. Use **Retry login** in the UI to force it.
- Apple asks for a new 2FA code every so often. The account card will show it.

## Ask AI

Each account has an **Ask AI** box. If the account has a problem it explains it and what to do; otherwise ask anything about the tracked devices. It uses a Home Assistant AI Task entity (`ai_task_entity`; empty uses the first one) and sends the account status and device list (with locations) to your AI provider.
