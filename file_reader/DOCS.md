# File Reader

Create and edit text files from the web UI. Each file becomes a sensor in Home Assistant through MQTT.
The sensor state is the **last line** of the file. The full text is in the `content` attribute.

## Settings

| Option | What it does |
| --- | --- |
| Files folder | Where files are saved. Must start with `/data`, `/share`, `/media`, `/homeassistant` or `/config`. |
| MQTT host / port | Your broker. The defaults work with the Mosquitto add-on. |
| MQTT username / password | Leave empty if your broker has no login. |

### Folder cheat sheet

| Path | Where it is |
| --- | --- |
| `/data/files` | Private to this add-on (default, hidden from you). |
| `/share/file_reader` | The `share` folder, visible in Samba and the File editor. Recommended. |
| `/media/file_reader` | The `media` folder. |
| `/homeassistant/file_reader` | Inside your Home Assistant config folder. |
| `/config/file_reader` | This add-on's own config folder. |

Use a **dedicated subfolder**. Every file in the folder becomes an MQTT sensor.

After changing the folder, restart the add-on. Existing files from `/data/files` are copied over once.

## Notes
- Only files directly inside the folder are used, not subfolders.
- Sensor attributes hold at most the last 8000 characters of a file.
