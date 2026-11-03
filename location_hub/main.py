import asyncio, logging
import aiohttp
from aiohttp import web
import tracker  # sets up logging from the add-on options
import alerts

log = logging.getLogger("hub")
INDEX = "/app/www/index.html"

async def h_index(req):
    return web.FileResponse(INDEX, headers={"Cache-Control": "no-store"})

async def forever(name, fn):
    """Keep a background job alive: one failing never takes the other down."""
    while True:
        try:
            await fn()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("%s crashed, restarting in 10s", name)
        await asyncio.sleep(10)

async def main():
    async with aiohttp.ClientSession() as s:
        app = web.Application()
        app["session"] = s
        hub = alerts.App(tracker.entity_id)
        hub.http = s
        tracker.add_routes(app)
        app.add_routes([web.get("/", h_index)] + hub.routes())
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "0.0.0.0", 8099).start()
        log.info("Location Hub is up")
        await asyncio.gather(forever("tracker", lambda: tracker.run_background(s)),
                             forever("alerts", hub.ws_loop))

asyncio.run(main())
