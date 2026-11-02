# Work Hours Tracker

## Setup

1. Install and start the add-on.
2. Turn on **Show in sidebar** (Info tab).
3. Open **Work Hours** in the sidebar.
4. Tick each **person** you want to track. Under their name, tick the **zones**
   that count as work for *that person*, then press **Save**.

Every person has their own zone list, so one person can work at Site A while
someone else works at Site B and Site C. Someone standing in a zone that isn't
ticked for them is not logged.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `save_folder` | `/homeassistant/work_hours` | Where the files are saved. Must start with `/homeassistant/`, `/share/` or `/media/`. Created automatically. |
| `keep_days` | `365` | CSV rows older than this are deleted. `0` keeps everything forever. |
| `check_seconds` | `30` | How often locations are checked. |
| `grace_minutes` | `10` | How long someone can be outside the zone before the shift ends. |
| `min_minutes` | `5` | Visits shorter than this are ignored. |
| `period_start_day` | `Thursday` | The weekday a new pay period begins. |
| `period_weeks` | `1` | How many weeks a pay period lasts. |
| `period_anchor_date` | empty | Only for periods of 2+ weeks. Any date a pay period started on. |
| `history_periods` | `26` | How many finished pay periods the sensor remembers. |
| `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password` | empty | Only if you do **not** use the Mosquitto add-on. |

Changing options requires restarting the add-on. Changing people and zones in
the sidebar page takes effect immediately.

## Pay periods

The sensor shows the hours worked **in the current pay period**, then starts
again at zero when the next period begins (at midnight on the start day).

| `period_start_day` | `period_weeks` | Period |
| --- | --- | --- |
| Thursday | 1 | Thursday to the next Wednesday, then resets on Thursday |
| Thursday | 2 | Thursday to Wednesday two weeks later, then resets |
| Monday | 1 | Monday to Sunday |

For periods of 2 weeks or more the add-on needs to know *which* weeks are paired
together. Put any date a pay period started on in `period_anchor_date`, for
example `2026-10-29`. If you leave it empty, the add-on uses the most recent
start day from the first time it ran.

If you change the period length later, finished periods stay in the history
exactly as they were recorded, and the new length applies from now on.

## MQTT device

If MQTT is available, the add-on creates one device called **Work Hours
Tracker** in Home Assistant. No YAML needed, it appears on its own. For each
tracked person it adds:

- **`<Name> hours`**: a sensor whose state is the hours worked in the current pay period
- **`<Name> at work`**: on while the person is clocked in

The hours sensor has these attributes:

| Attribute | Meaning |
| --- | --- |
| `period_label`, `period_start`, `period_end` | The current pay period |
| `days_left` | Days left in the period, counting today |
| `today_hours`, `week_hours` | Hours today and this Monday-to-Sunday week |
| `last_period_hours` | Total for the previous pay period |
| `clocked_in`, `current_zone`, `clocked_in_since` | Live status |
| `history` | Totals for finished pay periods, newest first: `start`, `end`, `hours` |

The history keeps going even after old CSV rows are cleaned up by `keep_days`.
Periods with zero hours are left out.

The add-on uses the Mosquitto broker add-on automatically. If you use a
different broker, fill in the `mqtt_` options. If MQTT isn't available the
add-on still tracks hours and writes files, and tries MQTT again every 5 minutes.

Removing a person from the sidebar page removes their sensors.

## Files

Each person gets a CSV named after them. The name comes from the person
entity's name the first time they are saved, with spaces turned into
underscores, for example `Jonathan Gibson` becomes `Jonathan_Gibson.csv`:

```
date,zone,start,end,hours
2026-11-02,Work Site A,06:52,15:41,8.82
```

- A row is written when a visit **ends**. The sidebar page and the sensor
  include the current visit live, but it isn't in the file until the person leaves.
- The end time is when the person actually left, not when the grace period ran out.
- A visit that crosses midnight becomes two rows. The first ends at `24:00`.
- Lunch or errands shorter than the grace period do not split the shift.

Once a person's file name is set it never changes, even if you rename the
person in Home Assistant, so their history stays in one file. If two people
end up with the same name, the second gets `_2` on the end.

The files open in Excel, Numbers and Google Sheets.

## Cleanup

Every 6 hours (and at start-up) rows older than `keep_days` are removed. Before
that happens the add-on saves the totals of every pay period those rows
belong to, so the sensor history is not lost. Only CSV files with this add-on's
header are touched; other files in the folder are left alone.

## How it decides someone is "at work"

The add-on reads each person entity's state. If it matches the name of one of
the zones ticked for that person, the person is in that zone. If the person's
state is `unavailable` or `unknown`, nothing changes until a real state returns.

## Tips

- Make each zone at least **150 m** in radius, otherwise GPS drift will bounce
  people in and out.
- In the Companion app set Location permission to **Always** and turn on
  **Precise Location**.
- Compare the hours to a real timesheet for a couple of weeks before relying
  on them for pay.
- The sensor's entity ID is built from the device and person name, for example
  `sensor.work_hours_tracker_jonathan_gibson_hours`. You can rename it in HA.

## Troubleshooting

- **No people or zones listed:** check the Log tab for "Can't reach Home Assistant".
- **No MQTT device:** install and start the Mosquitto broker add-on and the MQTT
  integration, then restart this add-on. The bottom of the sidebar page shows
  the MQTT status.
- **Nothing is being saved:** the save folder must start with `/homeassistant/`,
  `/share/` or `/media/`. Anything else isn't mounted into the add-on.
- **Visits missing:** they may be shorter than `min_minutes`.
