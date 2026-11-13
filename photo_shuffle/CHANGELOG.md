# Changelog

## 4.0.2

- Now published as a prebuilt image (`ghcr.io/jonathangibson98/{arch}-addon-photo_shuffle`), so it installs without building on the Pi.
- The add-on page link now points at this repository.

## 4.0.1
- Fix: the image build failed for armv7. The Home Assistant base image no longer supports armv7, so Photo Hub now supports aarch64 and amd64 only.

## 2.0.0
- Photo Shuffle and Photo Puller merged into one add-on, Photo Hub
- Folder shuffles and Unsplash collections both publish over MQTT
- Single web UI with live previews and an activity log
