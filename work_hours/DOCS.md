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
| `keep_days` | `365` | Rows older than this are deleted. `0` keeps everything forever. |
| `check_seconds` | `30` | How often locations are checked. |
| `grace_minutes` | `10` | How long someone can be outside the zone before the shift ends. |
| `min_minutes` | `5` | Visits shorter than this are ignored. |

Changing options requires restarting the add-on. Changing people and zones in
the sidebar page takes effect immediately.

## Files

Each person gets a CSV named after them. The name comes from the person
entity's name the first time they are saved, with spaces turned into
underscores, for example `Jonathan Gibson` becomes `Jonathan_Gibson.csv`:

```
date,zone,start,end,hours
2026-11-02,Work Site A,06:52,15:41,8.82
```

- A row is written when a visit **ends**. The sidebar page shows the current
  visit live, but it isn't in the file until the person leaves.
- The end time is when the person actually left, not when the grace period ran out.
- A visit that crosses midnight becomes two rows. The first ends at `24:00`.
- Lunch or errands shorter than the grace period do not split the shift.

Once a person's file name is set it never changes, even if you rename the
person in Home Assistant, so their history stays in one file. If two people
end up with the same name, the second gets `_2` on the end.

Upgrading from 1.0.0: existing people keep their old file names and their zones
are copied to each person automatically.

The files open in Excel, Numbers and Google Sheets.

## Cleanup

Every 6 hours (and at start-up) rows older than `keep_days` are removed. Only
CSV files with this add-on's header are touched; other files in the folder are
left alone.

## How it decides someone is "at work"

The add-on reads each person entity's state. If it matches the name of one of
the zones ticked for that person, the person is in that zone. If the person's state is
`unavailable` or `unknown`, nothing changes until a real state returns.

## Tips

- Make each zone at least **150 m** in radius, otherwise GPS drift will bounce
  people in and out.
- In the Companion app set Location permission to **Always** and turn on
  **Precise Location**.
- Compare the hours to a real timesheet for a couple of weeks before relying
  on them for pay.

## Troubleshooting

- **No people or zones listed:** check the Log tab for "Can't reach Home Assistant".
- **Nothing is being saved:** the save folder must start with `/homeassistant/`,
  `/share/` or `/media/`. Anything else isn't mounted into the add-on.
- **Visits missing:** they may be shorter than `min_minutes`.
