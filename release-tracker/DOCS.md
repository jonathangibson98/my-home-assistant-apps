# Release Tracker

Track only the TV shows and movies you care about, and get told when they drop.

## Setup

1. Make a free account at [themoviedb.org](https://www.themoviedb.org), then go to Settings, then API, and request a key. Either the **API Key** or the long **API Read Access Token** works.
2. Start this add-on and open **Releases** in the sidebar.
3. In **Settings**, paste the key and save.
4. Go to **Add**, search for something, pick who cares about it, and tap **Track**.

## People

Type the names of the people who track things in **Settings** (example: `Jon, MJ`). When you add something you can tag one person, several, or nobody. Tap a name on a card in the Tracking tab to change it later.

Each person gets their own sensors, named after them:

| Entity | What it is |
|---|---|
| `sensor.release_tracker_jon_upcoming` | How many of Jon's items release inside the window. Full list in the `items` attribute. |
| `binary_sensor.release_tracker_jon_releasing_today` | On when something Jon tracks releases today. Titles in the `titles` attribute. |

Rename someone in Settings and the old sensors are removed and new ones are created.

## Everyone's sensors

| Entity | What it is |
|---|---|
| `sensor.release_tracker_next_release` | Title of the next thing coming out. Attributes: `date`, `days_until`, `label`, `type`. |
| `sensor.release_tracker_upcoming` | Count of releases inside the window. List is in `items`. |
| `binary_sensor.release_tracker_releasing_today` | On when anything tracked releases today. `by_person` shows who it is for. |

## Settings

- **Region**: two-letter country code used for movie dates (US, GB, CA...).
- **Check every**: how often it asks TMDB for changes. 6 hours is plenty.
- **Show releases in the next**: the window for the "upcoming" counts.
- **MQTT broker**: leave blank to use the Mosquitto add-on. Fill it in if your broker lives somewhere else, like another Pi.

## Dashboard card

```yaml
type: markdown
title: Coming Soon
content: |
  {% for i in state_attr('sensor.release_tracker_upcoming','items') %}
  **{{ i.title }}**: {{ i.label }}, {{ i.date }} ({{ i.days_until }}d)
  {% endfor %}
```

## Notify one person

```yaml
alias: MJ release day
trigger:
  - platform: state
    entity_id: binary_sensor.release_tracker_mj_releasing_today
    to: "on"
action:
  - service: notify.notify
    data:
      title: Dropping today
      message: "{{ state_attr('binary_sensor.release_tracker_mj_releasing_today','titles') | join(', ') }}"
```

Swap `notify.notify` for the notify service of whoever should get it.

## Things to know

- Dates come from TMDB, which is crowd-sourced. TV air dates can be wrong or late, and streaming shows often have no date until shortly before release.
- Shows with no announced next episode say "No date announced yet" and get no sensor date.
- A movie that is already out stays in your list, but it will not show up as upcoming.
- Everything is stored in the add-on's own data folder and is included in Home Assistant backups.

## Troubleshooting

- **No entities show up**: check that MQTT is set up in Home Assistant. On the add-on's Settings tab, it should say "Connected to a broker."
- **Search says add your key**: paste the TMDB key in Settings and save.
- **Wrong or missing date**: hit **Refresh now**. If TMDB itself is wrong, there is nothing to fix on this end.
