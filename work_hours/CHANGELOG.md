# Changelog

All notable changes to this add-on are documented here.

## 1.2.0

- MQTT device "Work Hours Tracker" appears in Home Assistant automatically, with an hours sensor and an at-work sensor for each person
- Pick the pay period: start day (for example Thursday) and length in weeks
- The sensor state is the hours worked in the current pay period and resets when the next one starts
- Sensor attributes keep the history of totals for finished pay periods, even after old CSV rows are cleaned up
- The sidebar page now shows the pay period total next to today and this week
- Optional MQTT broker settings for people not using the Mosquitto add-on

## 1.1.0

- Each person now has their own list of work zones, so different people can be tracked at different locations
- Each person's file is named after them (from their person entity's name), for example `Jonathan_Gibson.csv`
- Settings from 1.0.0 are migrated automatically: everyone keeps their existing file and zones

## 1.0.0

- First release
- Sidebar page to pick which people and zones to track
- One CSV file per person
- Configurable save folder and data retention
- Grace period and minimum visit length
- Shifts crossing midnight are split into daily rows
