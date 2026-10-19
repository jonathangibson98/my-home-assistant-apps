# Changelog

## 2.6.0
- Added logging options to the Configuration tab: `log_level` (debug, info, warning, error) and `log_pyicloud` (Apple library debug output, off by default).
- Added log lines for logins, 2FA, fast mode on/off, device add/remove, MQTT discovery, and (at debug) every poll and zone distance.
- Passwords, 2FA codes, and email addresses are never written to the log. Accounts show by tab name.
- Web UI access logs are hidden unless `log_level` is debug.

## 2.5.1
- Fixed: the page said "Connected" while Apple was rejecting the login, and it never recovered.
- When Apple drops the session, the add-on now logs back in on its own (at most once every 30 minutes) and shows the 2FA code box if Apple wants a code.
- Added a **Reconnect** button when the last update failed.
- Added a **Change password** box on error, so a new Apple password doesn't mean removing the account.
- Fixed "1 days ago" to read "1 day ago".

## 2.5.0
- Added zone-aware polling. Near or inside a Home Assistant zone, the add-on polls fast. Away from zones, it uses your normal interval.
- New per-account settings: fast update seconds (0 = off, minimum 30, default 60) and how close to a zone counts as near (default 1500 m).
- Zones are read from Home Assistant every 5 minutes (needs `homeassistant_api` access).
- Fast mode is skipped for a device whose last location fix is over 30 minutes old.
- The account tab shows time until the next update and which device triggered fast mode.

## 2.4.0
- Accounts are now tabs across the top, with a **+ Add** tab. A ⚠️ on a tab means that account needs attention.
- Devices are added from a dropdown instead of a long checkbox list.
- Tracked devices show as short cards, each with a name box and a **Remove** button.
- Optional tab name for each account.

## 2.3.0
- Added custom names for devices. Type the name you want in Home Assistant when you add a device, or change it later and Save.
- Renaming changes the display name only. The entity ID stays as first created.

## 2.2.0
- Device rows now show battery level and when Apple last saw the device, like "iPhone 16 Pro Max · 85% · seen 3 min ago".

## 2.1.0
- Device rows now show an icon and the model (iPhone, Apple Watch, AirPods, Mac) so you can tell devices apart before adding them.
- Added add-on `icon.png` and `logo.png`.

## 2.0.0
- Rebuilt as a working add-on. The earlier version was a placeholder that did nothing.
- Multiple Apple IDs, each with its own devices and update interval.
- Built-in web page (sidebar) for adding accounts, entering the 2FA code, and picking devices.
- Devices appear in Home Assistant over MQTT as a `device_tracker` plus a battery sensor, with permanent unique IDs.
- Removing a device or account deletes its entities.
- Failed logins retry at most every 30 minutes, so Apple doesn't lock the account.
- The page only answers requests coming through Home Assistant's sidebar.
- Fixed `requirements.txt` (curly quotes broke the build) and trimmed unsupported architectures.
