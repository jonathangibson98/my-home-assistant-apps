# Jon's Home Assistant Apps

A collection of custom Home Assistant add-ons (apps). Add this repository once and every app below shows up in the Add-on Store.

---

## 🚀 Included Apps

| | App | What it does | Needs |
|---|---|---|---|
| 🤖 | [**AI Builder**](ai_builder) | Describe what you want in plain English and your `ai_task` entity builds automations, scenes, scripts, template sensors, helpers, AppDaemon apps, pyscripts, blueprints and even add-ons. Review the result, then tap **Create**. | An `ai_task` entity |
| 📣 | [**Announcement Maker**](ha-announcement-maker/announcement_maker) | Build AI-written voice announcements (weather, news, welcome home...) by ticking checkboxes. It writes the Home Assistant script and pushes it straight into HA. | An `ai_task` entity and a TTS engine |
| 🚪 | [**Arrival Alerts**](location_notifier) | AI "hype-man" arrival notifications, managed from a web UI. | Home Assistant API |
| 📄 | [**File Reader**](file_reader) | Web UI and MQTT file manager. Every text file in your folder becomes a Home Assistant sensor (last line as the state), plus an optional REST API for automations and logging. | MQTT |
| ☁️ | [**iCloud Lite**](ha-icloud-lite) | Track Apple devices from multiple iCloud accounts. Each device becomes a `device_tracker` with a battery sensor. | MQTT |
| 📍 | [**Location Tracker**](location_tracker) | Everyone's location as one sensor: a readable **City, State** for anyone who is away, a count of who is home, custom places, and a dashboard card generator. | MQTT (falls back to REST) |
| 📁 | [**Mobile File Manager & Samba**](mobile_ide) | Mobile-friendly file manager with folder uploads and a native Samba share. *(aarch64 only)* | none |
| 👤 | [**Personalized Info**](personalized_info) | Edit everyone's info and music preferences from a phone-friendly UI. Saved to one readable YAML file with automatic backups. | none (MQTT optional) |
| 🖼️ | [**Photo Shuffle**](photo_shuffle) | Add as many photo folders as you like. Each one becomes an image entity that shuffles on a timer, with a "Next photo" button. | MQTT |
| 🎬 | [**Release Tracker**](release-tracker) | Pick the TV shows and movies you care about and get sensors for what is coming out and when. | Free TMDB API key |
| 🏈 | [**Team Tracker Lite**](team_tracker_lite) | One lightweight live sports sensor. Pick any team from a menu, with a calendar of every game for your saved teams. | MQTT |
| ⏱️ | [**Work Hours Tracker**](work_hours) | Logs how long each person spends in the work zones you pick for them, saved as one CSV per person. | Home Assistant zones |

Each app has its own **Documentation** tab in Home Assistant, and a `DOCS.md` / `README.md` in its folder with setup details.

---

## 🛠️ Installation in Home Assistant

1. Open **Home Assistant**.
2. Go to **Settings** -> **Add-ons** -> **Add-on Store**.
3. Click the three dots in the upper right corner and select **Repositories**.
4. Add the URL of this repository:

   ```text
   https://github.com/jonathangibson98/my-home-assistant-apps
   ```

5. Close the dialog, refresh the page, and the apps appear in the store.
6. Pick one, click **Install**, then **Start**. Turn on **Show in sidebar** for apps that have a web UI.

### Apps that use MQTT

Install the **Mosquitto broker** add-on and set up the **MQTT** integration first. The apps detect the broker automatically, so you normally don't need to enter any MQTT details.

---

## 📂 Repository layout

```text
my-home-assistant-apps/
├── ai_builder/
├── file_reader/
├── ha-announcement-maker/announcement_maker/
├── ha-icloud-lite/
├── location_notifier/
├── location_tracker/
├── mobile_ide/
├── personalized_info/
├── photo_shuffle/
├── release-tracker/
├── team_tracker_lite/
├── work_hours/
└── repository.yaml
```
