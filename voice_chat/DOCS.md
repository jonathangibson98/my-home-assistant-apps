# Voice Chat

Talk to any Home Assistant AI agent hands-free. Your voice is captured in the browser, the agent you pick answers, and the reply is **spoken on the media player you pick**.

```
mic (phone/browser) → speech-to-text → conversation agent → text-to-speech → media player
```

## Configuration

| Option | What to put |
|---|---|
| `conversation_agent` | The AI entity to talk to, e.g. `conversation.home_assistant`, `conversation.ollama`, `conversation.google_generative_ai`. Find it under Settings → Voice assistants, or Developer tools → States (filter `conversation.`). |
| `media_player` | The speaker the replies play on, e.g. `media_player.kitchen_speaker`. |
| `tts_entity` | The text-to-speech engine, e.g. `tts.piper` or `tts.home_assistant_cloud`. |
| `stt_entity` | Speech-to-text engine, e.g. `stt.faster_whisper`. Leave empty to use the browser's built-in recognition (Chrome/Edge/Safari only, needs internet). |
| `language` | Optional. Leave empty to use Home Assistant's language. Set it if your STT/TTS engines need a specific code (`en-US`, `de`, ...). |
| `hands_free` | On: keeps listening after every reply, like a phone call. Off: one question per tap. |
| `silence_ms` | How long you must pause before your sentence is sent (default 1200). |
| `volume` | 0 leaves the speaker's volume alone; 0.1–1 sets it before each reply. |
| `password` | Only needed for the direct HTTPS page (below). |
| `certfile` / `keyfile` | Certificate names in `/ssl`. If they don't exist a self-signed one is generated. |

If an entity ID is wrong, the page shows a banner listing the entity IDs that do exist.

## Using it

Open **Voice Chat** in the sidebar, pick a speaker from the **Speaker** menu if you don't want the default, and tap the mic. Talk, pause, and the reply plays on your speaker. The mic is paused while the speaker talks, so it won't hear itself. Tap the orb to send early, cancel, or stop the speaker. **New chat** starts a fresh conversation with the agent.

## Which device listens, which device speaks

- **Speaks:** the speaker chosen in the page's Speaker menu (default: `media_player` from Configuration). Any media player entity works, as long as `tts.speak` can play on it.
- **Listens:** the microphone of the phone, tablet or PC that has the page open. Google and Alexa speakers don't share their microphones with Home Assistant, so they can only speak. To listen from a room, open the page on a wall tablet there.

## Microphone access

Browsers only allow the microphone on secure pages. Try the sidebar panel first. If the mic is blocked (common in the Home Assistant mobile app):

1. Set a `password`, save, restart the add-on.
2. In the add-on's **Network** section, set a host port for `8443/tcp` and restart.
3. Open `https://<your-ha-address>:8443`, accept the certificate warning (or use a real certificate from `/ssl`), enter the password.

The direct page is off unless a password is set, because it can otherwise drive your AI agent without logging in.

## Troubleshooting

- **"Speech recognition failed"**: set `language` to a code your STT engine supports.
- **Reply shows but nothing plays**: confirm `tts_entity` works with `media_player` via Developer tools → Actions → `tts.speak`.
- **Cuts in on itself**: raise `silence_ms`, or move the speaker away from the phone.
- Add-on log shows each exchange and any config problems.
