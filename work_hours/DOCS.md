# Work Hours Tracker

## Setup

1. Install and start the add-on.
2. Turn on **Show in sidebar** (Info tab).
3. Open **Work Hours** in the sidebar.
4. Tick the **people** to track and the **zones** that count as work, then press **Save**.

You can pick as many zones as you like. Every ticked person is tracked in
every ticked zone.

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

Each person gets a CSV named after their person entity, for example
`person.jon` becomes `jon.csv`:

```
date,zone,start,end,hours
2026-11-02,Work Site A,06:52,15:41,8.82
```

- A row is written when a visit **ends**. The sidebar page shows the current
  visit live, but it isn't in the file until the person leaves.
- The end time is when the person actually left, not when the grace period ran out.
- A visit that crosses midnight becomes two rows. The first ends at `24:00`.
- Lunch or errands shorter than the grace period do not split the shift.

The files open in Excel, Numbers and Google Sheets.

## Cleanup

Every 6 hours (and at start-up) rows older than `keep_days` are removed. Only
CSV files with this add-on's header are touched; other files in the folder are
left alone.

## How it decides someone is "at work"

The add-on reads each person entity's state. If it matches the name of one of
the ticked zones, the person is in that zone. If the person's state is
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
