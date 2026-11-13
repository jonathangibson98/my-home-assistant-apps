#!/usr/bin/env python3
"""Clean up what the Home Assistant add-on linter complains about.

Run from the root of the repo:   python3 fix_addon_lint.py
Add --dry-run to only list what would change.

It edits every add-on config (config.yaml / config.json) and:
  * removes options that only repeat the default:
      startup: application, boot: auto, ingress_port: 8099, panel_admin: true
  * removes empty `options: {}` and `schema: {}`
  * removes the obsolete `watchdog:` line, and adds a Docker HEALTHCHECK
    to that add-on's Dockerfile in its place
  * removes deprecated architectures (armv7, armhf, i386) from `arch`
"""
import json
import re
import sys
from pathlib import Path

DRY = "--dry-run" in sys.argv
OLD_ARCH = {"armv7", "armhf", "i386"}

# top-level YAML lines to drop (whole line must match)
YAML_DROP = [
    re.compile(r"^startup:\s*['\"]?application['\"]?\s*(#.*)?$"),
    re.compile(r"^boot:\s*['\"]?auto['\"]?\s*(#.*)?$"),
    re.compile(r"^ingress_port:\s*['\"]?8099['\"]?\s*(#.*)?$"),
    re.compile(r"^panel_admin:\s*true\s*(#.*)?$"),
    re.compile(r"^options:\s*\{\}\s*(#.*)?$"),
    re.compile(r"^schema:\s*\{\}\s*(#.*)?$"),
]
WATCHDOG = re.compile(r"^watchdog:\s*(.+?)\s*$")
PORT = re.compile(r"\[PORT:(\d+)\]")
HEALTH = "HEALTHCHECK"


def health_line(url):
    m = re.search(r"\[PORT:(\d+)\](/\S*)?", url)
    port = m.group(1) if m else "8099"
    path = (m.group(2) if m and m.group(2) else "/health")
    return (
        "HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \\\n"
        f"  CMD wget -q -O /dev/null http://127.0.0.1:{port}{path} || exit 1\n"
    )


def fix_yaml(path):
    changes, watchdog = [], None
    out = []
    lines = path.read_text().splitlines()
    i = 0
    in_arch = False
    while i < len(lines):
        line = lines[i]
        m = WATCHDOG.match(line)
        if m:
            watchdog = m.group(1).strip("\"'")
            changes.append("removed watchdog")
            i += 1
            continue
        if any(p.match(line) for p in YAML_DROP):
            changes.append("removed " + line.split(":")[0])
            i += 1
            continue
        if re.match(r"^arch:\s*$", line):
            in_arch = True
            out.append(line)
            i += 1
            continue
        if in_arch:
            item = re.match(r"^\s*-\s*['\"]?(\w+)['\"]?\s*$", line)
            if item:
                if item.group(1) in OLD_ARCH:
                    changes.append("removed arch " + item.group(1))
                    i += 1
                    continue
            else:
                in_arch = False
        flow = re.match(r"^(arch:\s*)\[(.*)\]\s*$", line)
        if flow:
            items = [x.strip().strip("\"'") for x in flow.group(2).split(",") if x.strip()]
            kept = [x for x in items if x not in OLD_ARCH]
            if kept != items:
                changes.append("removed old arch")
                line = flow.group(1) + "[" + ", ".join(kept) + "]"
        out.append(line)
        i += 1
    if changes and not DRY:
        text = "\n".join(out).rstrip("\n") + "\n"
        text = re.sub(r"\n{3,}", "\n\n", text)
        path.write_text(text)
    return changes, watchdog


JSON_DROP = [
    re.compile(r'^\s*"startup":\s*"application",?\s*$'),
    re.compile(r'^\s*"boot":\s*"auto",?\s*$'),
    re.compile(r'^\s*"ingress_port":\s*8099,?\s*$'),
    re.compile(r'^\s*"panel_admin":\s*true,?\s*$'),
    re.compile(r'^\s*"options":\s*\{\s*\},?\s*$'),
    re.compile(r'^\s*"schema":\s*\{\s*\},?\s*$'),
]
JSON_WATCHDOG = re.compile(r'^\s*"watchdog":\s*"(.*)",?\s*$')


def fix_json(path):
    changes, watchdog, out = [], None, []
    for line in path.read_text().splitlines():
        m = JSON_WATCHDOG.match(line)
        if m:
            watchdog = m.group(1)
            changes.append("removed watchdog")
            continue
        if any(p.match(line) for p in JSON_DROP):
            changes.append("removed " + line.split('"')[1])
            continue
        flow = re.match(r'^(\s*"arch":\s*)\[(.*)\](,?)\s*$', line)
        if flow:
            items = [x.strip().strip('"') for x in flow.group(2).split(",") if x.strip()]
            kept = [x for x in items if x not in OLD_ARCH]
            if kept != items:
                changes.append("removed old arch")
                line = flow.group(1) + "[" + ", ".join('"%s"' % x for x in kept) + "]" + flow.group(3)
        out.append(line)
    text = "\n".join(out) + "\n"
    json.loads(text)  # make sure the result is still valid JSON
    if changes and not DRY:
        path.write_text(text)
    return changes, watchdog


def add_healthcheck(folder, url):
    df = folder / "Dockerfile"
    if not df.exists():
        return "no Dockerfile, add a HEALTHCHECK by hand"
    text = df.read_text()
    if HEALTH in text:
        return "Dockerfile already has a HEALTHCHECK"
    block = health_line(url)
    if not DRY:
        text = text.rstrip("\n")
        # put it before the last CMD/ENTRYPOINT line
        parts = re.split(r"(?m)^(?=CMD|ENTRYPOINT)", text)
        if len(parts) > 1:
            text = "".join(parts[:-1]) + block + "\n" + parts[-1]
        else:
            text += "\n\n" + block
        df.write_text(text.rstrip("\n") + "\n")
    return "added HEALTHCHECK to Dockerfile"


def main():
    configs = sorted(p for p in Path(".").rglob("config.*")
                     if p.suffix in (".yaml", ".yml", ".json") and ".git" not in p.parts
                     and "node_modules" not in p.parts)
    total = 0
    for cfg in configs:
        try:
            if cfg.suffix == ".json":
                data = json.loads(cfg.read_text())
                if "slug" not in data:
                    continue
                changes, wd = fix_json(cfg)
            else:
                if not re.search(r"(?m)^slug:", cfg.read_text()):
                    continue
                changes, wd = fix_yaml(cfg)
        except Exception as e:
            print(f"!! {cfg}: {e}")
            continue
        if wd:
            changes.append(add_healthcheck(cfg.parent, wd))
        if changes:
            total += 1
            print(f"{cfg}:")
            for c in changes:
                print("   -", c)
    print(("Would change" if DRY else "Changed"), total, "add-on config(s)")


main()
