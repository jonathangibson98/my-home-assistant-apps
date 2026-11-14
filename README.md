# Jon's Home Assistant Apps

A collection of custom Home Assistant add-ons (apps). Add this repository once and every app below shows up in the Add-on Store.

All apps support `aarch64` (Raspberry Pi 4/5) and `amd64`.

> Voice Chat, Personal AI Speech, Zone Creator and Pi Health Monitor live in the companion repository
> [pi-custom-features](https://github.com/jonathangibson98/pi-custom-features).

---

## Included apps

| App | Folder | What it does | Needs |
|---|---|---|---|
| **Creator & AI Builder** | [`ai_builder`](ai_builder) | Describe what you want in plain English and your `ai_task` entity builds automations, scenes, scripts, template sensors, helpers, AppDaemon apps, pyscripts, blueprints and even add-ons. Also makes AI voice announcements and dashboard facts, and backs up its own data. | An `ai_task` entity (a TTS engine and speaker for announcements) |
| **File Reader** | [`file_reader`](file_reader) | Web UI and MQTT file manager. Every text file in your folder becomes a Home Assistant sensor (last line as the state), plus an optional REST API for automations and logging. | MQTT |
| **iCloud Lite** | [`ha-icloud-lite`](ha-icloud-lite) | Track Apple devices from multiple iCloud accounts. Each device becomes a `device_tracker` with a battery sensor. | MQTT |
| **Location Hub** | [`location_hub`](location_hub) | A location history map (trails, playback, stops, places, heatmap) plus everyone's location sensor (you choose its name), switches, device trackers, a dashboard card generator and AI arrival alerts. One add-on, one sidebar entry. | MQTT; an `ai_task` entity and a `notify.*` service for alerts |
| **Person Profiles** | [`person_profiles`](person_profiles) | Builds one profile sensor per person from every entity linked to them, with optional AI summaries. | Nothing (an `ai_task` entity or conversation agent for AI summaries) |
| **Personalized Info** | [`personalized_info`](personalized_info) | Edit everyone's info and music preferences from a phone-friendly UI. Saved to one readable YAML file with automatic backups. | Nothing (MQTT optional) |
| **Photo Hub** | [`photo_shuffle`](photo_shuffle) | Folder shuffles and random Unsplash photos, all published as image entities. Manage everything from one web UI. | MQTT (an Unsplash key for Unsplash collections) |
| **Release Tracker** | [`release-tracker`](release-tracker) | Track anything with a release date, like TV shows, movies, video games and DLC, albums and artists, celebrities, tech launches, merch drops, events and sales, and get one sensor for what is coming out and when. | Free TMDB API key (TV, movies, celebrities); free Twitch Client ID and Secret for IGDB (games/DLC); MQTT. Music and custom items need nothing. |
| **SVG Maker** | [`svg_maker`](svg_maker) | Turn photos into clean, scalable SVG icons and vector files from the sidebar. Runs fully local. | Nothing |
| **Team Tracker Lite** | [`team_tracker_lite`](team_tracker_lite) | One lightweight live sports sensor. Pick any team from a menu, with a calendar of every game for your saved teams. | MQTT |
| **Work Hours Tracker** | [`work_hours`](work_hours) | Logs how long each person spends in the work zones you pick for them, saved as one file per person, with MQTT sensors. | Home Assistant zones (MQTT optional) |

Each app has its own **Documentation** tab in Home Assistant, plus a `DOCS.md` / `README.md` in its folder with setup details.

---

## Installation in Home Assistant

1. Open **Home Assistant**.
2. Go to **Settings** -> **Add-ons** -> **Add-on Store**.
3. Click the three dots in the upper right corner and select **Repositories**.
4. Add the URL of this repository:

   ```text
   https://github.com/jonathangibson98/my-home-assistant-apps
   ```

5. Close the dialog, refresh the page, and the apps appear in the store.
6. Pick one, click **Install**, then **Start**. Turn on **Show in sidebar** for apps that have a web UI.

Home Assistant has to be able to clone the repository, so it must be **public** (or you must use a URL with an access token).

### Apps that use MQTT

Install the **Mosquitto broker** add-on and set up the **MQTT** integration first. The apps detect the broker automatically, so you normally don't need to enter any MQTT details.

---

## Prebuilt images (GitHub packages)

Every app's `config.yaml` has an `image:` line, so Home Assistant downloads a finished image from GitHub's container registry instead of building it on your Pi. The images are built by the **Publish add-on images to GHCR** workflow ([`.github/workflows/create.yml`](.github/workflows/create.yml)) and are named `ghcr.io/jonathangibson98/<arch>-addon-<slug>`, tagged with the app version and `latest`.

Publishing a new version:

1. Bump `version` in the app's `config.yaml` and add an entry to its `CHANGELOG.md`.
2. Commit and push to `main`. No tag or release is needed. The workflow builds `aarch64` and `amd64` images only for apps whose current `version` has no image yet.
3. The first time an app is published, open your GitHub profile, **Packages**, the new package, **Package settings**, and set it to **Public**. Home Assistant cannot pull a private package.

To rebuild everything (for example after a base image update), open the **Actions** tab, choose **Publish add-on images to GHCR**, click **Run workflow** and tick **force**.

The image tag is the `version` in `config.yaml`, so Home Assistant only finds an image after you push that exact version.

## Checks

The **Validate** workflow ([`.github/workflows/validate.yml`](.github/workflows/validate.yml)) runs on every push and pull request, by hand, and nightly. For every add-on it checks the file structure, runs the Home Assistant add-on linter and Hadolint on the Dockerfile, and builds the image (amd64). It also runs yamllint and a Python syntax check across the repo.

---

## Repository layout

```text
my-home-assistant-apps/
├── .github/
│   ├── workflows/
│   │   ├── create.yml        (publish images to GHCR)
│   │   └── validate.yml      (lint, build and sanity checks)
│   ├── ISSUE_TEMPLATE/
│   ├── CODEOWNERS
│   ├── dependabot.yml
│   └── pull_request_template.md
├── ai_builder/               (Creator & AI Builder)
├── file_reader/
├── ha-icloud-lite/           (iCloud Lite, slug icloud_lite)
├── location_hub/
├── person_profiles/
├── personalized_info/
├── photo_shuffle/            (Photo Hub)
├── release-tracker/          (slug release_tracker)
├── svg_maker/
├── team_tracker_lite/
├── work_hours/
├── .hadolint.yaml
├── .yamllint
├── repository.yaml
└── README.md
```

Add-on folders have to stay at the top level of the repo for Home Assistant to find them.
