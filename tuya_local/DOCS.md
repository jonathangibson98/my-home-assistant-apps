# Tuya Local: Documentation

## What you need

- The **Mosquitto broker** add-on (or your own MQTT broker, set in this add-on's Configuration).
- Home Assistant and your Tuya devices on the same network. This add-on runs on the **host network** so it can hear the devices' UDP announcements.
- For the QR login: the Smart Life or Tuya Smart app on your phone.

## Setup in five minutes

1. **Account tab, Import from LocalTuya** (only if you used LocalTuya). Nothing is changed in LocalTuya. Then switch LocalTuya off for the devices you move, because **a Tuya device only accepts one local connection at a time**.
2. **Account tab, sign in**: in the app go to *Me → Settings (gear) → Account and Security → User Code*, copy the code, paste it here, tap *Show QR code*, then scan the code with the app's scan icon and approve. Tap **Get my devices**. This fetches every device's current local key and its list of data points, once.
3. **Find tab, Scan now**: devices on your network show up with their IP address. Saved devices get their IP address updated.
4. **Devices tab**: each device connects by itself. Open *Entities in Home Assistant* to rename an entity or hide one you do not want. The *On / Off* buttons let you test a switch or light.

New entities appear in Home Assistant under the device (Settings → Devices). Home Assistant names them from the device name and entity name, so rename the device on the Settings panel *before* you rely on its entity IDs.

## When a device will not connect

Open the device and tap **Check connection**. It tests, in order: is the device heard on the network, does its port answer, and which protocol version and key work. The text at the bottom says what to do. The usual causes:

| What you see | Cause | Fix |
|---|---|---|
| "The device refuses the connection" | Something else holds the device's single local connection: the Tuya Smart / Smart Life app open on a phone, LocalTuya, another add-on. | Close the phone apps, switch the other integration off, wait a minute. |
| "Connected, but the reply could not be read" | The local key or protocol version is wrong. Re-pairing a device in the app creates a new key. | Account tab → **Get my devices**. |
| "The device does not answer" | Unplugged, weak Wi-Fi, or a new IP address. | Find tab → **Scan now**. Give the device a fixed IP in your router. |

The add-on tries every protocol version by itself and remembers the one that works.

## Entities

| Tuya data point | Home Assistant entity |
|---|---|
| on/off, settable | switch |
| on/off, read only | binary sensor |
| list of choices, settable | select |
| number, settable | number (with its range and unit) |
| number or text, read only | sensor (power, voltage, current, energy, battery, temperature and humidity get the right device class) |
| lights (`switch_led`, brightness, colour temperature, colour) | one light |

Things that are not mapped by hand (vacuums, climate, covers, fans) still work: their data points show up as switches, selects, numbers and sensors you can use in automations. Older lights that use the first-generation colour format (`colour_data` without `_v2`) are brightness and colour temperature only. Data points named *countdown* are hidden by default.

If the account has no data point list for a device (or you added it by hand), the add-on reads what the device reports and makes a switch for each on/off value and a sensor for each other value.

## Where things are stored

Everything is in the add-on's private data folder (`/data/tuya.json`), including your login token and each device's local key. It is not written to `/config`. The web page only answers requests that come through Home Assistant.

## MQTT topics

Entities publish to `tuya_local/<device id>/<entity id>/state` and listen on `.../set`. Availability is `tuya_local/<device id>/available` and `tuya_local/status`.
