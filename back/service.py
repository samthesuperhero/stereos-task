from __future__ import annotations

import asyncio
import logging
import signal

from back.config import Settings
from back.http import Application, HttpServer, sd_notify

logger = logging.getLogger(__name__)


async def run_service(settings: Settings) -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_stop() -> None:
        stop.set()

    for signal_number in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signal_number, request_stop)
        except NotImplementedError:
            signal.signal(
                signal_number,
                lambda _signum, _frame: loop.call_soon_threadsafe(request_stop),
            )

    application = Application(settings)
    server = HttpServer(application, settings)
    await server.start()
    logger.info(
        "Service ready",
        extra={"structured": {"host": settings.host, "port": settings.port}},
    )
    await sd_notify("READY=1")
    try:
        await stop.wait()
    finally:
        await sd_notify("STOPPING=1")
        try:
            await asyncio.wait_for(server.close(), settings.shutdown_timeout_seconds)
        except Exception:
            logger.exception("HTTP server cleanup failed")
        logger.info("Service stopped")
