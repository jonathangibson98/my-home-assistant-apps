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

Who tracks what shows up in the `by_person` attribute of the release sensor (see below). Renaming or removing someone updates it right away.

## The release sensor

Everything comes through **one** sensor: `sensor.release_tracker_releases`. Shows, movies, games, and DLC are all in it.

The state is how many releases land inside your window (Settings, Updates). The details are attributes:

| Attribute | What it is |
|---|---|
| `items` | The list of releases inside the window, soonest first (up to 30). Each has `title`, `type` (TV, Movie, or Game), `date`, `days_until`, `label`, and `people`. |
| `next_title`, `next_date`, `next_days_until`, `next_label`, `next_type` | The very next thing coming out, even if it is past the window. |
| `today_count`, `today` | How many things drop today, and their titles. |
| `by_person` | For each person, the titles of their releases inside the window. |
| `window_days`, `tracked_count` | Your window setting, and how many items you track. |

If you updated from an older version, the old sensors (`next_release`, `upcoming`, `releasing_today`, `upcoming_games`, and the per-person ones) are removed from Home Assistant on startup. They may linger as greyed-out entries in the entity list until you delete them there.

## Games and DLC

Games use a different free service (IGDB, run by Twitch), so it needs its own keys.

1. Go to [dev.twitch.tv/console](https://dev.twitch.tv/console) and log in. Twitch makes you turn on two-factor login first if you have not.
2. Tap **Register Your Application**. Name it anything, set OAuth Redirect URL to `http://localhost`, pick **Application Integration** as the category, and create it.
3. Open **Manage** on the new app. Copy the **Client ID**, then tap **New Secret** and copy that too.
4. In this add-on go to **Settings**, paste both under **Video games (IGDB)**, and save.
5. On the **Add** tab flip the switch to **Games & DLC**, search, and tap **Track**.

Track the main game and any DLC or expansion IGDB knows about shows up on its own. The card shows whichever thing drops next, like `DLC: Skin Pack`. You can also search a DLC by name and track it alone.

Games show up in the same release sensor as everything else, with `type` set to `Game`. Tag who is tracking a game just like a show.

Notify when something drops today:

```yaml
alias: Release drops today
trigger:
  - platform: time
    at: "08:00:00"
condition:
  - condition: template
    value_template: >
      {{ state_attr('sensor.release_tracker_releases','today_count') | int > 0 }}
action:
  - service: notify.notify
    data:
      title: Dropping today
      message: "{{ state_attr('sensor.release_tracker_releases','today') | join(', ') }}"
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
  {% for i in state_attr('sensor.release_tracker_releases','items') %}
  **{{ i.title }}** ({{ i.type }}): {{ i.label }}, {{ i.date }} ({{ i.days_until }}d)
  {% endfor %}
```

Show only one person's releases:

```yaml
type: markdown
title: MJ's releases
content: |
  {% for i in state_attr('sensor.release_tracker_releases','items') if 'MJ' in i.people %}
  **{{ i.title }}**: {{ i.label }}, {{ i.date }}
  {% endfor %}
```

## Notify one person

```yaml
alias: MJ release day
trigger:
  - platform: time
    at: "08:00:00"
condition:
  - condition: template
    value_template: >
      {{ state_attr('sensor.release_tracker_releases','items')
         | selectattr('days_until','eq',0) | selectattr('people','contains','MJ') | list | count > 0 }}
action:
  - service: notify.notify
    data:
      title: Dropping today
      message: >
        {{ state_attr('sensor.release_tracker_releases','items')
           | selectattr('days_until','eq',0) | selectattr('people','contains','MJ')
           | map(attribute='title') | join(', ') }}
```

Swap `notify.notify` for the notify service of whoever should get it.

## Things to know

- Game dates come from IGDB, also crowd-sourced. Dates are the earliest across all platforms. If only a month or year is known it says "expected" and gets no date.
- Dates come from TMDB, which is crowd-sourced. TV air dates can be wrong or late, and streaming shows often have no date until shortly before release.
- Shows with no announced next episode say "No date announced yet" and get no date.
- A movie that is already out stays in your list, but it will not show up as upcoming.
- Everything is stored in the add-on's own data folder and is included in Home Assistant backups. The Backup card makes extra copies you can reach in the share folder.

## Troubleshooting

- **No entities show up**: check that MQTT is set up in Home Assistant. On the add-on's Settings tab, it should say "Connected to a broker."
- **Search says add your key**: paste the TMDB key in Settings and save.
- **Games search says add your Twitch keys**: paste both the Client ID and Secret in Settings and save.
- **Wrong or missing date**: hit **Refresh now**. If TMDB itself is wrong, there is nothing to fix on this end.
