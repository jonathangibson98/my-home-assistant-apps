"""mitmproxy script used by the Cloud Intelligence tab. Reads only responses that contain an accessToken and
appends the plug's device name, access key, access token and product key to a short-lived file in /tmp that the
add-on's page reads. Nothing is written to /data."""
import json
import os

OUT = os.environ.get("CI_KEYS_FILE", "/tmp/ci_keys.json")


def _maybe_json(value):
    if isinstance(value, str) and "accessToken" in value:
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def find_keys(obj, context=None):
    obj = _maybe_json(obj)
    if isinstance(obj, dict):
        here = {**(context or {}), **{k: v for k, v in obj.items() if k in ("deviceName", "productKey") and isinstance(v, str)}}
        if isinstance(obj.get("accessKey"), str) and isinstance(obj.get("accessToken"), str):
            yield {"deviceName": here.get("deviceName", ""), "accessKey": obj["accessKey"],
                   "accessToken": obj["accessToken"], "productKey": here.get("productKey", "")}
        for value in obj.values():
            yield from find_keys(value, here)
    elif isinstance(obj, list):
        for value in obj:
            yield from find_keys(value, context)


class KeyCapture:
    def response(self, flow):
        resp = getattr(flow, "response", None)
        if resp is None:
            return
        try:
            text = resp.get_text(strict=False)
        except Exception:
            return
        if not text or "accessToken" not in text:
            return
        try:
            data = json.loads(text)
        except ValueError:
            return
        try:
            with open(OUT) as f:
                found = json.load(f)
        except (OSError, ValueError):
            found = []
        for k in find_keys(data):
            if not any(x["deviceName"] == k["deviceName"] and x["accessKey"] == k["accessKey"] and x["accessToken"] == k["accessToken"] for x in found):
                found.append(k)
        with open(OUT, "w") as f:
            json.dump(found, f)
        os.chmod(OUT, 0o600)


addons = [KeyCapture()]
