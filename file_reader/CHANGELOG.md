# Changelog

## 1.1.0

### Added
- New **Files folder** option: pick where your files live (for example `/share/file_reader`).
- Add-on logo and icon.
- Changelog tab, Documentation tab and friendly option labels in the add-on settings.
- Web UI now shows the version, the folder in use, MQTT status and the changelog.
- Files from the old `/data/files` folder are copied once into a newly chosen folder.

### Fixed
- Add-on crashing on start with current `paho-mqtt` (version 2.x).
- MQTT never reconnecting if the broker started after the add-on. It now retries and re-syncs all sensors.
- File names are checked, so nobody can read or write outside the files folder.
- File names with quotes or special characters no longer break or inject into the web page.
- Deleting a file now also clears its state and attributes from MQTT.
- Very large files no longer overload Home Assistant sensor attributes (content is capped at 8000 characters, the end of the file is kept).
- `secrets.yaml` is never listed or exposed.

### Changed
- Removed old 32-bit architectures and the unused `schema_version` key.
- MQTT password is now hidden in the settings.

## 1.0.1
- Initial version: web UI and MQTT sensors for text files.
