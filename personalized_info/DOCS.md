# Personalized Info: Documentation

## Where the data lives

| What | Path |
|---|---|
| Main data file | `/homeassistant/ai_memory/people.yaml` |
| Backups (last 5) | `/homeassistant/ai_memory/backups/` |

## Using the UI

- **Save** writes the file. Nothing is saved until you press it. The bottom bar says "Unsaved changes" when you have edits pending.
- **+ field** adds a text value, **+ list** adds a one-per-line list, **+ group** adds a nested section.
- **✕** deletes a field. **Delete person** removes the whole card.
- Music genres and artists are one entry per line.

## Notes

- If two copies of the app run at once, the last save wins.
- The `homeassistant_config:rw` mapping is what lets the app read and write your config folder.
