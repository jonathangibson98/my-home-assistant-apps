# Changelog

## 1.2.0

- **Robot vacuums**: a device page now has a **Robot vacuum setup** panel. It guesses which data points are the status, start/pause, mode and battery, you check the numbers, and it creates one proper Home Assistant vacuum (start, pause, stop, return to dock, battery, status, optional fan speed and find-my-robot). Cloud sync sets this up on its own for vacuums it recognises.
- **Friendly names for modes**: every select (and the vacuum's fan speeds) has a **Name the options** box. Type a friendly name next to each raw value; Home Assistant shows and sends the friendly one.
- **No more "DP n" clutter**: unnamed data points are now off by default, there is a **Hide all unnamed "DP n" entities** button, and setting up the vacuum hides the data points it replaces.
- Fixed doubled names like "Living Room Lamp Living Lamp".

## 1.1.0

- **One Home Assistant device**: every entity from every Tuya device now lives under a single device called **Tuya Local**, instead of one device per lamp or plug. Each entity name starts with the Tuya device's name (for example `Dresser Lamp Light`), so entity IDs read `light.dresser_lamp_light`. Entities keep their unique IDs, so history and dashboards carry over. The old per-device entries are left empty in Settings → Devices: delete them there.

## 1.0.0

First release.

- **Find devices**: listens for Tuya devices on your network and shows each one's IP address and protocol version. Devices you already added are moved to their new IP address automatically.
- **Check connection**: a step by step test for one device (is it on the network, does port 6668 answer, which protocol version and key work) that says in plain words what is wrong, and fixes the protocol version and IP address when it can.
- **Sign in with a QR code** (Smart Life / Tuya Smart app, no developer account) to fetch every device's local key and data point list from your Tuya account, once.
- **Import from LocalTuya**: brings in the devices, IP addresses, keys and entities saved in LocalTuya.
- **Local control** over protocol 3.1 to 3.5, with automatic protocol detection and automatic reconnects. Devices are published to Home Assistant with MQTT discovery: switches, lights (brightness, colour temperature, colour), numbers, selects, sensors and binary sensors.
- Rename entities or hide the ones you do not want from the device card.
