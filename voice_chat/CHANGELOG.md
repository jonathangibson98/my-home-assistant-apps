# Changelog

## 1.0.0

- First release.
- Hands-free voice conversation with any Home Assistant conversation agent.
- Replies are spoken on the media player chosen in the add-on configuration.
- Speech-to-text through a Home Assistant STT entity, or the browser's built-in recognition when none is set.
- Automatic silence detection, with push-to-talk style single turns when `hands_free` is off.
- Tap the orb to send early, cancel, or stop the speaker; New chat resets the conversation.
- Optional direct HTTPS page (port 8443, password protected, self-signed certificate generated if none is in `/ssl`).
- Config check: wrong or missing entity IDs are listed in the page and the add-on log, with the IDs that do exist.
