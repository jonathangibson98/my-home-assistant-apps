import csv
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests
from flask import Flask, jsonify, request, send_file

TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
API = "http://supervisor/core/api"
HEADERS = {"Authorization": f"Bearer {TOKEN}"}

with open("/data/options.json") as f:
    OPTS = json.load(f)

FOLDER = OPTS.get("save_folder", "/homeassistant/work_hours").rstrip("/")
KEEP_DAYS = int(OPTS.get("keep_days", 365))
CHECK = int(OPTS.get("check_seconds", 30))
GRACE = int(OPTS.get("grace_minutes", 10))
MIN_MIN = int(OPTS.get("min_minutes", 5))

SETTINGS = "/data/settings.json"
SESSIONS = "/data/sessions.json"
HEADER = ["date", "zone", "start", "end", "hours"]

lock = threading.RLock()
_tz = None
app = Flask(__name__)


# ---------- helpers ----------
def ha(path):
    r = requests.get(API + path, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()


def tz():
    global _tz
    if _tz is None:
        try:
            _tz = ZoneInfo(ha("/config")["time_zone"])
        except Exception:
            return ZoneInfo("UTC")
    return _tz


def now():
    return datetime.now(tz())


def load_json(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f)
    os.replace(tmp, path)


def csv_path(pid):
    return os.path.join(FOLDER, pid.split(".", 1)[1] + ".csv")


def read_rows(pid):
    rows = []
    try:
        with open(csv_path(pid), newline="") as f:
            for r in csv.DictReader(f):
                try:
                    float(r["hours"])
                    rows.append(r)
                except Exception:
                    pass
    except FileNotFoundError:
        pass
    except Exception as e:
        print("Read error:", e, flush=True)
    return rows


def log_session(pid, zone, start, end):
    """Write one finished visit to the person's file (split at midnight)."""
    if (end - start).total_seconds() < MIN_MIN * 60:
        return
    rows = []
    cur = start
    while cur < end:
        midnight = datetime.combine(
            cur.date() + timedelta(days=1), datetime.min.time(), tzinfo=cur.tzinfo
        )
        seg_end = min(end, midnight)
        hrs = (seg_end - cur).total_seconds() / 3600
        end_label = "24:00" if seg_end == midnight else seg_end.strftime("%H:%M")
        rows.append([cur.date().isoformat(), zone, cur.strftime("%H:%M"), end_label, f"{hrs:.2f}"])
        cur = seg_end
    os.makedirs(FOLDER, exist_ok=True)
    p = csv_path(pid)
    new = not os.path.exists(p)
    with open(p, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HEADER)
        w.writerows(rows)


def cleanup():
    """Delete rows older than keep_days. 0 = keep forever."""
    if KEEP_DAYS <= 0 or not os.path.isdir(FOLDER):
        return
    cutoff = (now().date() - timedelta(days=KEEP_DAYS)).isoformat()
    for name in os.listdir(FOLDER):
        if not name.endswith(".csv"):
            continue
        p = os.path.join(FOLDER, name)
        try:
            with open(p, newline="") as f:
                rows = list(csv.reader(f))
            if not rows or rows[0] != HEADER:
                continue  # not one of our files, leave it alone
            kept = [rows[0]] + [r for r in rows[1:] if r and r[0] >= cutoff]
            if len(kept) != len(rows):
                tmp = p + ".tmp"
                with open(tmp, "w", newline="") as f:
                    csv.writer(f).writerows(kept)
                os.replace(tmp, p)
                print(f"Cleaned {len(rows) - len(kept)} old rows from {name}", flush=True)
        except Exception as e:
            print("Cleanup error:", e, flush=True)


# ---------- tracking ----------
def tick():
    with lock:
        s = load_json(SETTINGS, {"people": [], "zones": []})
        sessions = load_json(SESSIONS, {})

    zone_names = {}
    for zid in s["zones"]:
        try:
            st = ha(f"/states/{zid}")
            zone_names[zid] = st["attributes"].get("friendly_name", zid).lower()
        except Exception as e:
            print("Zone lookup failed:", zid, e, flush=True)

    t = now()

    # people removed from the list: close their open visit
    for pid in list(sessions):
        if pid not in s["people"]:
            sess = sessions[pid]
            end = datetime.fromisoformat(sess["left_at"]) if sess.get("left_at") else t
            try:
                log_session(pid, sess["zone"], datetime.fromisoformat(sess["start"]), end)
                del sessions[pid]
            except Exception as e:
                print("Write failed:", e, flush=True)

    for pid in s["people"]:
        try:
            state = ha(f"/states/{pid}")["state"]
        except Exception as e:
            print("Person lookup failed:", pid, e, flush=True)
            continue
        if state in ("unavailable", "unknown"):
            continue

        cur = None
        for zid, name in zone_names.items():
            if state.lower() == name:
                cur = state
                break

        sess = sessions.get(pid)
        if sess:
            if cur == sess["zone"]:
                sess["left_at"] = None
            else:
                if not sess.get("left_at"):
                    sess["left_at"] = t.isoformat()
                left = datetime.fromisoformat(sess["left_at"])
                if cur is not None or (t - left).total_seconds() >= GRACE * 60:
                    try:
                        log_session(pid, sess["zone"], datetime.fromisoformat(sess["start"]), left)
                        del sessions[pid]
                        sess = None
                    except Exception as e:
                        print("Write failed (will retry):", e, flush=True)
                        continue
        if pid not in sessions and cur:
            sessions[pid] = {"zone": cur, "start": t.isoformat(), "left_at": None}

    with lock:
        save_json(SESSIONS, sessions)


def worker():
    last_clean = 0
    while True:
        try:
            tick()
        except Exception as e:
            print("Tick error:", e, flush=True)
        if time.time() - last_clean > 6 * 3600:
            cleanup()
            last_clean = time.time()
        time.sleep(CHECK)


# ---------- web UI ----------
@app.get("/")
def index():
    return send_file("/app/index.html")


@app.get("/api/state")
def api_state():
    with lock:
        s = load_json(SETTINGS, {"people": [], "zones": []})
        sessions = load_json(SESSIONS, {})

    err = None
    people, zones = [], []
    try:
        for e in ha("/states"):
            eid = e["entity_id"]
            nm = e["attributes"].get("friendly_name", eid)
            if eid.startswith("person."):
                people.append({"id": eid, "name": nm})
            elif eid.startswith("zone."):
                zones.append({"id": eid, "name": nm})
    except Exception as ex:
        err = f"Can't reach Home Assistant: {ex}"

    names = {p["id"]: p["name"] for p in people}
    t = now()
    today = t.date().isoformat()
    week_start = t.date() - timedelta(days=t.weekday())
    week = week_start.isoformat()
    midnight = datetime.combine(t.date(), datetime.min.time(), tzinfo=t.tzinfo)
    week_mid = datetime.combine(week_start, datetime.min.time(), tzinfo=t.tzinfo)

    status = []
    for pid in s["people"]:
        rows = read_rows(pid)
        td = sum(float(r["hours"]) for r in rows if r["date"] == today)
        wk = sum(float(r["hours"]) for r in rows if r["date"] >= week)
        live = None
        sess = sessions.get(pid)
        if sess:
            start = datetime.fromisoformat(sess["start"])
            td += max(0, (t - max(start, midnight)).total_seconds() / 3600)
            wk += max(0, (t - max(start, week_mid)).total_seconds() / 3600)
            live = {"zone": sess["zone"], "since": start.strftime("%b %d, %I:%M %p")}
        status.append({
            "id": pid,
            "name": names.get(pid, pid),
            "today": round(td, 2),
            "week": round(wk, 2),
            "live": live,
            "file": csv_path(pid),
            "recent": rows[-8:][::-1],
        })

    return jsonify({
        "error": err,
        "people": people,
        "zones": zones,
        "settings": s,
        "status": status,
        "info": {"folder": FOLDER, "keep_days": KEEP_DAYS, "grace": GRACE, "min": MIN_MIN},
    })


@app.post("/api/settings")
def api_settings():
    data = request.get_json(force=True) or {}
    people = [x for x in data.get("people", []) if re.fullmatch(r"person\.[a-z0-9_]+", str(x))]
    zones = [x for x in data.get("zones", []) if re.fullmatch(r"zone\.[a-z0-9_]+", str(x))]
    with lock:
        save_json(SETTINGS, {"people": people, "zones": zones})
    return jsonify({"ok": True})


if __name__ == "__main__":
    threading.Thread(target=worker, daemon=True).start()
    app.run(host="0.0.0.0", port=8099, threaded=True)
