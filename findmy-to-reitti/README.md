# Find My to Reitti

Home Assistant add-on that forwards your **Find My / iCloud device locations** to your self-hosted **Reitti** server, so your iPhones, iPads, and other Apple devices show up in your Reitti timeline.

Apple has no Find My API you can point at a URL. This add-on gets around that by reading the device trackers created by Home Assistant's **Apple iCloud** integration and posting each new location to Reitti's OwnTracks-format endpoint.

## Features

- Add and edit everything from a sidebar web UI. No YAML.
- Any number of devices, each with its own name, device ID, and on/off switch
- Per-device token override, so different people can land in different Reitti users
- "Send now" button and a status line showing the last result for each device
- Only sends when a location changes, so a parked iPad won't spam Reitti
- Supports `aarch64` (Raspberry Pi) and `amd64`

## Quick start

1. Set up the **Apple iCloud** integration in Home Assistant.
2. Create an API token in Reitti under **Settings → API Tokens**.
3. Install this add-on, start it, and open **Find My to Reitti** from the sidebar.
4. Enter your Reitti address and token, add your devices, and hit **Save**.

Full instructions are on the **Documentation** tab.
