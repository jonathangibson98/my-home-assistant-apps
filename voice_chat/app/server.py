#!/usr/bin/env python3
"""Voice Chat add-on.

Browser mic -> (HA speech-to-text) -> HA conversation agent -> HA text-to-speech
-> media player. The web page only captures the microphone and shows the
transcript; every reply is spoken on the media player chosen in the add-on config.
"""
import asyncio
import hmac
import json
import logging
import os
import re
import ssl
import subprocess
import time
from pathlib import Path

from aiohttp import ClientError, ClientSession, ClientTimeout, web

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("voice_chat")

OPTIONS = json.loads(Path("/data/options.json").read_text())
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA_API = "http://supervisor/core/api"
INGRESS_IP = "172.30.32.2"  # Home Assistant's ingress proxy
APP_DIR = Path(__file__).parent

SESSION: ClientSession | None = None
_lang_cache: str | None = None


class HAError(Exception):
    pass


def opt(key: str) -> str:
    return str(OPTIONS.get(key) or "").strip()


async def ha(method: str, path: str, *, headers=None, **kwargs):
    h = {"Authorization": f"Bearer {SUPERVISOR_TOKEN}"}
    if headers:
        h.update(headers)
    try:
        async with SESSION.request(method, HA_API + path, headers=h, **kwargs) as r:
            text = await r.text()
            if r.status >= 400:
                raise HAError(f"Home Assistant returned {r.status} for {path}: {text[:300]}")
            return json.loads(text) if text else None
    except asyncio.TimeoutError:
        raise HAError(f"Home Assistant timed out on {path}")
    except ClientError as e:
        raise HAError(f"Could not reach Home Assistant: {e}")


async def language() -> str:
    global _lang_cache
    if opt("language"):
        return opt("language")
    if not _lang_cache:
        cfg = await ha("GET", "/config")
        _lang_cache = (cfg or {}).get("language", "en")
    return _lang_cache


def clean_for_tts(text: str) -> str:
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    text = re.sub(r"[*_`#>~|]+", "", text)
    text = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F]", "", text)
    return re.sub(r"\s+", " ", text).strip()


def reply_text(result) -> str:
    try:
        return result["response"]["speech"]["plain"]["speech"] or ""
    except (KeyError, TypeError):
        return ""


def chosen_speaker(request, body=None) -> str:
    """Speaker picked on the page, falling back to the configured one."""
    value = str((body or {}).get("media_player") or request.query.get("mp") or "").strip()
    if re.fullmatch(r"media_player\.[a-z0-9_]+", value):
        return value
    return opt("media_player")


async def speak(text: str, mp: str) -> None:
    message = clean_for_tts(text)
    if not message:
        return
    volume = float(OPTIONS.get("volume") or 0)
    if volume > 0:
        await ha("POST", "/services/media_player/volume_set",
                 json={"entity_id": mp, "volume_level": volume})
    data = {
        "entity_id": opt("tts_entity"),
        "media_player_entity_id": mp,
        "message": message,
        "cache": False,
    }
    if opt("language"):
        data["language"] = opt("language")
    await ha("POST", "/services/tts/speak", json=data)


async def wait_playback(mp: str) -> None:
    """Block until the media player has started and then finished playing."""
    start = time.monotonic()
    started = False
    while True:
        elapsed = time.monotonic() - start
        if elapsed > 180:
            return
        try:
            state = ((await ha("GET", f"/states/{mp}")) or {}).get("state")
        except HAError:
            return
        if state in ("playing", "buffering"):
            started = True
        elif started:
            return
        elif elapsed > 10:  # never started playing
            return
        await asyncio.sleep(0.4)


async def compute_status() -> dict:
    states = await ha("GET", "/states")
    by_id = {s["entity_id"]: s for s in states}

    def available(domain: str) -> str:
        found = sorted(i for i in by_id if i.startswith(domain + "."))
        return ", ".join(found) or "none found"

    def name(entity_id: str) -> str:
        if not entity_id:
            return "not set"
        return by_id.get(entity_id, {}).get("attributes", {}).get("friendly_name") or entity_id

    problems = []
    for key, domain in (("conversation_agent", "conversation"),
                        ("media_player", "media_player"),
                        ("tts_entity", "tts")):
        value = opt(key)
        if not value:
            problems.append(f"Set “{key}” in the add-on Configuration tab. Available: {available(domain)}")
        elif value not in by_id:
            problems.append(f"“{value}” ({key}) doesn’t exist. Available: {available(domain)}")
    speakers = sorted(
        ({"entity_id": i, "name": name(i)} for i in by_id if i.startswith("media_player.")),
        key=lambda x: x["name"].lower())
    stt = opt("stt_entity")
    if stt and stt not in by_id:
        problems.append(f"“{stt}” (stt_entity) doesn’t exist. Available: {available('stt')}")

    return {
        "problems": problems,
        "media_player": opt("media_player"),
        "speakers": speakers,
        "stt_entity": stt,
        "hands_free": bool(OPTIONS.get("hands_free", True)),
        "silence_ms": int(OPTIONS.get("silence_ms") or 1200),
        "language": await language(),
        "names": {
            "conversation_agent": name(opt("conversation_agent")),
            "media_player": name(opt("media_player")),
        },
    }


# ---------------------------------------------------------------- routes

async def index(request):
    return web.FileResponse(APP_DIR / "index.html", headers={"Cache-Control": "no-store"})


async def status(request):
    return web.json_response(await compute_status())


async def stt(request):
    entity = opt("stt_entity")
    if not entity:
        raise HAError("No stt_entity is set in the add-on configuration.")
    audio = await request.read()
    lang = await language()
    header = ("format=wav; codec=pcm; sample_rate=16000; bit_rate=16; channel=1; "
              f"language={lang}")
    result = await ha("POST", f"/stt/{entity}", data=audio,
                      headers={"X-Speech-Content": header})
    if not result or result.get("result") != "success":
        raise HAError("Speech recognition failed. Check the language option matches your STT engine.")
    return web.json_response({"text": result.get("text", "")})


async def chat(request):
    body = await request.json()
    text = str(body.get("text", "")).strip()
    if not text:
        return web.json_response({"error": "Empty message"}, status=400)
    payload = {
        "text": text,
        "language": await language(),
        "agent_id": opt("conversation_agent"),
    }
    if body.get("conversation_id"):
        payload["conversation_id"] = body["conversation_id"]
    result = await ha("POST", "/conversation/process", json=payload)
    reply = reply_text(result) or "I didn’t get a reply from the agent."
    log.info("You: %s | Agent: %s", text, reply[:120])
    if body.get("speak", True):
        await speak(reply, chosen_speaker(request, body))
    return web.json_response({"text": reply, "conversation_id": (result or {}).get("conversation_id")})


async def wait(request):
    await wait_playback(chosen_speaker(request))
    return web.json_response({"ok": True})


async def stop(request):
    await ha("POST", "/services/media_player/media_stop", json={"entity_id": chosen_speaker(request)})
    return web.json_response({"ok": True})


@web.middleware
async def guard(request, handler):
    # Ingress traffic is already authenticated by Home Assistant. Anything else
    # (the direct HTTPS port) must send the password for every API call.
    if request.path.startswith("/api/") and request.remote != INGRESS_IP:
        password = opt("password")
        sent = request.headers.get("X-Voice-Token", "")
        if not password or not hmac.compare_digest(sent.encode(), password.encode()):
            return web.json_response({"error": "Unauthorized"}, status=401)
    try:
        return await handler(request)
    except HAError as e:
        log.warning("%s", e)
        return web.json_response({"error": str(e)}, status=502)
    except web.HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("Unhandled error")
        return web.json_response({"error": f"Unexpected error: {e}"}, status=500)


# ---------------------------------------------------------------- startup

def make_ssl_context() -> ssl.SSLContext:
    cert = Path("/ssl") / opt("certfile")
    key = Path("/ssl") / opt("keyfile")
    if cert.is_file() and key.is_file():
        log.info("Direct HTTPS page uses certificate %s", cert)
    else:
        cert, key = Path("/data/selfsigned.crt"), Path("/data/selfsigned.key")
        if not cert.is_file():
            log.info("No certificate in /ssl, generating a self-signed one")
            subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
                 "-keyout", str(key), "-out", str(cert), "-subj", "/CN=homeassistant.local",
                 "-addext", "subjectAltName=DNS:homeassistant.local,DNS:homeassistant"],
                check=True, capture_output=True)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)
    return ctx


async def main():
    global SESSION
    SESSION = ClientSession(timeout=ClientTimeout(total=300))
    app = web.Application(middlewares=[guard], client_max_size=16 * 1024 * 1024)
    app.add_routes([
        web.get("/", index),
        web.get("/api/status", status),
        web.post("/api/stt", stt),
        web.post("/api/chat", chat),
        web.post("/api/wait", wait),
        web.post("/api/stop", stop),
    ])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", 8099).start()
    if opt("password"):
        await web.TCPSite(runner, "0.0.0.0", 8443, ssl_context=make_ssl_context()).start()
        log.info("Direct HTTPS page listening on port 8443 (map it under Network)")
    else:
        log.info("Direct HTTPS page is off. Set a password in Configuration to turn it on.")

    try:
        for problem in (await compute_status())["problems"]:
            log.warning("Config problem: %s", problem)
    except HAError as e:
        log.warning("Startup check skipped: %s", e)

    await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
