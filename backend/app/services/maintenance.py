from __future__ import annotations

import asyncio
import contextlib
import logging

from backend.app.services.admin_cleanup import run_scheduled_cleanup

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 3600


def run_cleanup_once() -> dict[str, int]:
    # Keep the scheduler on the same scoped implementation and lock as manual
    # maintenance.  It therefore preserves live sessions, active dataset
    # references, and usage_unknown/provider_overrun holds.
    return run_scheduled_cleanup()


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
