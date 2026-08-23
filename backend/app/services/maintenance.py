from __future__ import annotations

import asyncio
import contextlib
import logging

from backend.app.services.ppt import cleanup_expired
from backend.app.services.usage import purge_expired_entities, sweep_stale_reservations

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 3600


def run_cleanup_once() -> dict[str, int]:
    stats: dict[str, int] = {"files": cleanup_expired(), "reservations": sweep_stale_reservations()}
    stats.update(purge_expired_entities())
    return {key: value for key, value in stats.items() if value}


async def periodic_cleanup_loop() -> None:
    while True:
        await asyncio.sleep(_INTERVAL_SECONDS)
        try:
            stats = await asyncio.to_thread(run_cleanup_once)
            if stats: logger.info("maintenance cleanup: %s", stats)
        except Exception:
            logger.exception("maintenance cleanup failed")


def start_periodic_cleanup() -> asyncio.Task:
    return asyncio.create_task(periodic_cleanup_loop())


async def stop_periodic_cleanup(task: asyncio.Task | None) -> None:
    if task is None: return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
