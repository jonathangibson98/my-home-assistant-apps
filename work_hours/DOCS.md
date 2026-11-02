# Work Hours Tracker

## Setup

1. Install and start the add-on.
2. Turn on **Show in sidebar** (Info tab).
3. Open **Work Hours** in the sidebar.
4. Under **Pay period**, choose the start day and length.
5. Under **People**, pick a person from the drop-down and press **Add person**.
   Then add the **work zones** for that person from their zone drop-down.
6. Press **Save**.

Only the people you add are shown, so there's no long list to scroll through.
Press **Edit** on a person to change their zones, or **Remove** to stop
tracking them.

Every person has their own zone list, so one person can work at Site A while
someone else works at Site B and Site C. Someone standing in a zone that isn't
added for them is not logged.

## Options

| Option | Default | What it does |
| --- | --- | --- |
| `save_folder` | `/homeassistant/work_hours` | Where the files are saved. Must start with `/homeassistant/`, `/share/` or `/media/`. Created automatically. |
| `keep_days` | `365` | CSV rows older than this are deleted. `0` keeps everything forever. |
| `check_seconds` | `30` | How often locations are checked. |
| `grace_minutes` | `10` | How long someone can be outside the zone before the shift ends. |
| `min_minutes` | `5` | Visits shorter than this are ignored. |
| `mqtt_host`, `mqtt_port`, `mqtt_username`, `mqtt_password` | empty | Only if you do **not** use the Mosquitto add-on. |

Changing options requires restarting the add-on. Everything on the sidebar
page (people, zones and the pay period) takes effect as soon as you press Save.

## Pay periods

Set these in the **Pay period** box on the sidebar page.

The sensor shows the hours worked **in the current pay period**, then starts
again at zero when the next period begins (at midnight on the start day).

| Starts on | Length | Period |
| --- | --- | --- |
| Thursday | 1 week | Thursday to the next Wednesday, then resets on Thursday |
| Thursday | 2 weeks | Thursday to Wednesday two weeks later, then resets |
| Monday | 1 week | Monday to Sunday |

- **A pay period started on** only matters for periods of 2 weeks or more. It
  tells the add-on which weeks are paired together. Pick any date a pay period
  began, for example `2026-10-29`. It is moved back to the start day
  automatically if it falls on a different weekday.
- **Periods of history to keep** is how many finished pay periods the sensor
  remembers in its `history` attribute.

If you change the period later, finished periods stay in the history exactly
as they were recorded, and the new length applies from now on.

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
- **The person I want isn't in the drop-down:** only people already added are
  hidden from it. Check the person exists under Settings → People in Home Assistant.
- **No MQTT device:** install and start the Mosquitto broker add-on and the MQTT
  integration, then restart this add-on. The bottom of the sidebar page shows
  the MQTT status.
- **Nothing is being saved:** the save folder must start with `/homeassistant/`,
  `/share/` or `/media/`. Anything else isn't mounted into the add-on.
- **Visits missing:** they may be shorter than `min_minutes`.
