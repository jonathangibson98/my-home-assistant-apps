# Release Tracker

Track only the TV shows, movies, games, and DLC you care about, and get told when they drop.

## Setup

1. Make a free account at [themoviedb.org](https://www.themoviedb.org), then go to Settings, then API, and request a key. Either the **API Key** or the long **API Read Access Token** works.
2. Start this add-on and open **Releases** in the sidebar.
3. In **Settings**, paste the key and save.
4. Go to **Add**, search for something, pick who cares about it, and tap **Track**.

## People

Manage everyone in **Settings, People**. Type a name and tap **Add**. Each person has **Rename** and **Remove** next to their name, and changes save right away.

- **Rename** moves all of that person's tags to the new name.
- **Remove** takes their tag off every tracked item and deletes their sensors.

When you add something, pick who is tracking it (shows, movies, **and games**), or nobody. Tap a name on a card in the Tracking tab to change it later.

Each person gets their own sensors, named after them:

| Entity | What it is |
|---|---|
| `sensor.release_tracker_jon_upcoming` | How many of Jon's items release inside the window. Full list in the `items` attribute. |
| `binary_sensor.release_tracker_jon_releasing_today` | On when a show or movie Jon tracks releases today. Titles in the `titles` attribute. |
| `sensor.release_tracker_jon_upcoming_games` | How many of Jon's games or DLC release inside the window. Full list in `items`. Also `titles_today`, `next_title`, `next_date`, `next_days_until`, `next_label`. |

Rename someone and the old sensors are removed and new ones are created.

## Everyone's sensors

| Entity | What it is |
|---|---|
| `sensor.release_tracker_next_release` | Title of the next thing coming out. Attributes: `date`, `days_until`, `label`, `type`. |
| `sensor.release_tracker_upcoming` | Count of releases inside the window. List is in `items`. |
| `binary_sensor.release_tracker_releasing_today` | On when anything tracked releases today. `by_person` shows who it is for. |

## Games and DLC

Games use a different free service (IGDB, run by Twitch), so it needs its own keys.

1. Go to [dev.twitch.tv/console](https://dev.twitch.tv/console) and log in. Twitch makes you turn on two-factor login first if you have not.
2. Tap **Register Your Application**. Name it anything, set OAuth Redirect URL to `http://localhost`, pick **Application Integration** as the category, and create it.
3. Open **Manage** on the new app. Copy the **Client ID**, then tap **New Secret** and copy that too.
4. In this add-on go to **Settings**, paste both under **Video games (IGDB)**, and save.
5. On the **Add** tab flip the switch to **Games & DLC**, search, and tap **Track**.

Track the main game and any DLC or expansion IGDB knows about shows up on its own. The card shows whichever thing drops next, like `DLC: Skin Pack`. You can also search a DLC by name and track it alone.

Games have their own sensor and never touch the TV and movie sensors. Tag who is tracking a game just like a show, and each person also gets `sensor.release_tracker_<name>_upcoming_games` (see People above). The main sensor also has a `by_person` attribute listing each person's games inside the window.

| Entity | What it is |
|---|---|
| `sensor.release_tracker_upcoming_games` | How many games or DLC release inside the window. Full list in `items`. Also `next_title`, `next_date`, `next_days_until`, `next_label`. |

Notify when something drops today:

```yaml
alias: Game drops today
trigger:
  - platform: time
    at: "08:00:00"
condition:
  - condition: template
    value_template: >
      {{ state_attr('sensor.release_tracker_upcoming_games','next_days_until') == 0 }}
action:
  - service: notify.notify
    data:
      title: Dropping today
      message: "{{ state_attr('sensor.release_tracker_upcoming_games','next_title') }}: {{ state_attr('sensor.release_tracker_upcoming_games','next_label') }}"
```

## Settings

Settings are split into cards. Tap a card to open it. Each card has its own **Save** button, and a badge on the card shows whether it is ready.

- **People**: add, rename, and remove who tracks things. Saves right away.
- **Movies & TV**: your TMDB key, and the two-letter region used for movie dates (US, GB, CA...).
- **Games (IGDB)**: your Twitch Client ID and Secret.
- **Updates**: how often it checks for changes (6 hours is plenty), and the window for the "upcoming" counts.
- **Home Assistant (MQTT)**: leave blank to use the Mosquitto add-on. Fill it in if your broker lives somewhere else, like another Pi.
- **Backup**: see below.

## Backup

Backups are saved as files in the Home Assistant **share** folder, so you can grab them from Samba, SSH, or the File editor.

- **Save to folder**: any folder under `/share/`. The default is `/share/release_tracker`. It is created for you.
- **Automatic backups**: Off, Daily, or Weekly. **Back up now** saves one right away.
- **Keep the newest**: older automatic backups are deleted past this number.
- **Include API keys and passwords**: off by default. Turn it on only if you want a backup that restores your keys too.
- **Saved backups**: lists what is in the folder. Tap **Restore** on one to replace your tracked list, tags, and settings with it. A safety copy of what you had is saved first and is never deleted automatically.

A backup holds your tracked list, who tags what, and your settings. If it was saved without keys, restoring leaves your current keys alone.

Backups need the share folder to be available to the add-on. After updating from an older version, restart the add-on. If the Backup card says the share folder is not available, reinstall or rebuild the add-on so the new access takes effect.

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

- Game dates come from IGDB, also crowd-sourced. Dates are the earliest across all platforms. If only a month or year is known it says "expected" and gets no sensor date.
- Dates come from TMDB, which is crowd-sourced. TV air dates can be wrong or late, and streaming shows often have no date until shortly before release.
- Shows with no announced next episode say "No date announced yet" and get no sensor date.
- A movie that is already out stays in your list, but it will not show up as upcoming.
- Everything is stored in the add-on's own data folder and is included in Home Assistant backups. The Backup card makes extra copies you can reach in the share folder.

## Troubleshooting

- **No entities show up**: check that MQTT is set up in Home Assistant. On the add-on's Settings tab, it should say "Connected to a broker."
- **Search says add your key**: paste the TMDB key in Settings and save.
- **Games search says add your Twitch keys**: paste both the Client ID and Secret in Settings and save.
- **Wrong or missing date**: hit **Refresh now**. If TMDB itself is wrong, there is nothing to fix on this end.
