# Find My to Reitti: Documentation

## What you need first

1. **Home Assistant** with the **Apple iCloud** integration set up (Settings → Devices & services → Add integration → Apple iCloud). Your devices should show up as `device_tracker.*` entities.
2. A running **Reitti** server that Home Assistant can reach over your network.
3. A Reitti **API token** (Reitti → Settings → API Tokens).

## Setup

1. Start the add-on and enable **Show in sidebar**.
2. Open **Find My to Reitti** from the sidebar.
3. Under **Reitti**, enter:
   - **Reitti address**, e.g. `http://192.168.1.50:8181`
   - **Default API token**
   - **Check interval**, how often (in seconds) the add-on looks for new locations. The minimum is 10 and the default is 30.
4. Under **Devices**, click **Add device** for each Find My device, then hit **Save**.
5. Click **Send now** on a device. A ✅ means Reitti accepted the point.

## Device settings

| Field | What it does |
|---|---|
| **On** | Turns forwarding for that device on or off. |
| **Name** | Label shown in the add-on. |
| **Find My device** | The `device_tracker` or `person` entity to follow. |
| **Device ID** | The 2 to 4 letter ID sent to Reitti. Leave it blank to auto-generate one from the name. |
| **Token override** | Uses a different Reitti token for this device. Leave it blank to use the default. Set it for another person's devices so they land in their own Reitti user. |

## How it works

Every check interval, the add-on reads each enabled device's current location from Home Assistant. If the location is newer than the last one it sent, it posts this to Reitti:

```
POST {Reitti address}/api/v1/ingest/owntracks?token={token}
{"_type":"location","tid":"JN","lat":..,"lon":..,"acc":..,"tst":..}
```

Settings are saved in the add-on's own `/data` folder, so they survive restarts and updates. Changing any setting resends each device's current location once.

## Troubleshooting

**The device dropdown is empty.** The Apple iCloud integration isn't set up yet, or it has no devices. Check that your devices appear under Developer Tools → States.

**❌ "No location yet".** The entity exists but has no GPS attributes yet. Wait for the next iCloud refresh.

**❌ "Home Assistant can't find ...".** The entity was renamed or removed. Pick the device again.

**❌ "Reitti said 401/403".** The token is wrong. Make a new one in Reitti and paste it in.

**❌ Connection error.** Check the Reitti address and port. The add-on needs to reach it from the Home Assistant host, so use the server's LAN IP rather than `localhost`.

**Updates suddenly stop.** Apple makes you re-verify the iCloud integration every so often. Open Settings → Devices & services → Apple iCloud and re-authenticate.

## Good to know

- iCloud updates every few minutes, so your timeline will be choppier than with a dedicated tracking app. For smoother tracking, use the Home Assistant Companion app or Overland.
- AirTags generally don't appear in the Apple iCloud integration.
- Tokens are sent in the URL over plain HTTP. That's fine on a home network, but use HTTPS if Reitti is exposed to the internet.
- The web UI is only reachable through Home Assistant's login, but tokens are saved unencrypted in the add-on's data folder.
