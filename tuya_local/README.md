# Tuya Local

Finds your Tuya (Smart Life) devices on your network, tells you why one stopped connecting, and controls them directly over your network. No cloud is needed after the first setup. It is a replacement for LocalTuya: every device shows up in Home Assistant as switches, lights, sensors, numbers and selects, created with MQTT discovery.

## Features

- **Find**: lists every Tuya device that announces itself on your network, with its IP address and protocol version. Saved devices follow their IP address when it changes.
- **Check connection**: a step by step test for one device that says in plain words what is wrong, and fixes the protocol version and IP address when it can.
- **Keys without a developer account**: sign in with a QR code from the Smart Life / Tuya Smart app to fetch every device's local key and data points.
- **Import from LocalTuya**: brings in the devices, IP addresses, keys and entities saved in LocalTuya.
- **Local control**: protocol 3.1 to 3.5 with automatic detection and automatic reconnects.

Open **Tuya Local** from the sidebar. See the Documentation tab for setup steps and what to do when a device will not connect.
