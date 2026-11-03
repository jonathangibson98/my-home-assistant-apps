# Changelog

## 1.2.0

- Type to the AI as well as talk: a message box under the chat. Replies to typed messages are spoken on the chosen speaker by default; untick "Speak replies to typed messages" to read them silently. Typing and talking share the same conversation.

## 1.1.0

- Speaker picker on the page: switch between any of your media players (Google, Sonos, Alexa and others) without touching the add-on configuration. Your choice is remembered per browser; the `media_player` option is the default.

## 1.0.0

- First release.
- Hands-free voice conversation with any Home Assistant conversation agent.
- Replies are spoken on the media player chosen in the add-on configuration.
- Speech-to-text through a Home Assistant STT entity, or the browser's built-in recognition when none is set.
- Automatic silence detection, with push-to-talk style single turns when `hands_free` is off.
- Tap the orb to send early, cancel, or stop the speaker; New chat resets the conversation.
- Optional direct HTTPS page (port 8443, password protected, self-signed certificate generated if none is in `/ssl`).
- Config check: wrong or missing entity IDs are listed in the page and the add-on log, with the IDs that do exist.
