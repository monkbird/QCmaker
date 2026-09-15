"""Persistent transition events for local dependencies and budget holds."""
from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from backend.app.core.admin_security import get_admin_settings
from backend.app.repositories.database import transaction
from backend.app.services.audit import record_operation_event_tx

logger = logging.getLogger(__name__)


def observe_state(key: str, state: str, *, category: str, message: str, healthy: bool) -> bool:
    """One event per transition, including recovery, across process restarts."""
    with transaction(immediate=True) as db:
        meta_key = f'event_state:{key}'
        row = db.execute('SELECT meta_value FROM admin_security_meta WHERE meta_key=?', (meta_key,)).fetchone()
        previous = row['meta_value'] if row else None
        if previous == state:
            return False
        # Initial healthy observations establish a baseline without noise.
        emitted = previous is not None or not healthy
        if emitted:
            record_operation_event_tx(db, level='info' if healthy else 'warning', category=category,
                                      event_key=f'{key}:recovered' if healthy else f'{key}:alert',
                                      message=message, context={'state': state, 'previous_state': previous})
        db.execute('INSERT INTO admin_security_meta(meta_key,meta_value) VALUES(?,?) ON CONFLICT(meta_key) DO UPDATE SET meta_value=excluded.meta_value', (meta_key, state))
    return emitted


def collect_local_events() -> None:
    if not get_admin_settings().enabled:
        return
    from backend.app.services.admin_metrics import budget_view, health_view
    health = health_view()
    labels = {'database': '数据库', 'wal': '数据库日志', 'data': '数据目录', 'generated_ppts': '成果目录', 'logs': '日志目录', 'chroma': '知识库'}
    for check in health['checks']:
        name, state = check['name'], check['status']
        healthy = state == 'ok'
        label = labels.get(name, name)
        observe_state(f'dependency:{name}', state, category='system', healthy=healthy,
                      message=f'{label}已恢复正常' if healthy else f'{label}需要检查')
    budget = budget_view()
    for field, label in [('usage_unknown_usd', '未知成本占用'), ('provider_overrun_usd', '供应商超额')]:
        active = Decimal(budget[field]) > 0
        observe_state(f'budget:{field}', 'active' if active else 'clear', category='usage', healthy=not active,
                      message=f'{label}需要核对' if active else f'{label}已解除')


async def monitor_local_events() -> None:
    while True:
        try:
            await asyncio.to_thread(collect_local_events)
        except Exception:
            # Events are operational hints, never a replacement for audit.
            logger.exception('local operational event collection failed')
        await asyncio.sleep(60)
