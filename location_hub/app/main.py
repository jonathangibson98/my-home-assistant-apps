"""Location Hub entry point."""
from __future__ import annotations

import asyncio
import logging
import os
import signal

import aiohttp
from aiohttp import web

import hub

VERSION = os.environ.get("MT_VERSION") or "3.3.0"
ADMIN_ALLOW = {"172.30.32.2", "127.0.0.1", "::1"} | set(filter(None, os.environ.get("MT_ADMIN_ALLOW", "").split(",")))


def env(name: str, default: str) -> str:
    return os.environ.get(name, default)


async def health(request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


@web.middleware
async def admin_guard(request: web.Request, handler):
    """Only reachable through HA ingress (the Supervisor proxy). /health is open for the watchdog."""
    if request.path != "/health" and request.remote not in ADMIN_ALLOW and not os.environ.get("MT_DEV"):
        return web.Response(status=403, text="Forbidden: use Home Assistant ingress")
    resp = await handler(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "no-referrer")
    if request.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


async def main() -> None:
    level = env("MT_LOG_LEVEL", "info").upper()
    logging.basicConfig(level=getattr(logging, level, logging.INFO),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    log = logging.getLogger("location_hub")
    log.info("Location Hub %s starting", VERSION)

    http = aiohttp.ClientSession()
    app = web.Application(middlewares=[admin_guard], client_max_size=8 * 1024 * 1024)
    app.router.add_get("/health", health)
    tasks = hub.setup(app, http)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", int(env("MT_ADMIN_PORT", "8099"))).start()
    log.info("Admin UI (ingress) on :%s", env("MT_ADMIN_PORT", "8099"))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass
    await stop.wait()

    log.info("Shutting down")
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await runner.cleanup()
    await http.close()


if __name__ == "__main__":
    asyncio.run(main())
