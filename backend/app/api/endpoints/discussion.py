import asyncio
import contextlib
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.core.errors import AppException
from backend.app.core.security import check_websocket_rate_limit, verify_websocket_token
from backend.app.repositories.database import connect
from backend.app.services.discussion_session import accept_command, execute, pending_commands

logger = logging.getLogger(__name__)
router = APIRouter()


def _protocol_error(session_id: str, message: str) -> dict:
    return {"type": "error", "session_id": session_id, "event_seq": 0, "timestamp": "", "error": {"code": "WS_PROTOCOL_ERROR", "message": message}, "recoverable": False}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    if not await verify_websocket_token(websocket): return
    if not await check_websocket_rate_limit(websocket): return
    active_session = None
    last_seq = 0
    tasks: set[asyncio.Task] = set()
    send_lock = asyncio.Lock()

    async def send(payload):
        async with send_lock: await websocket.send_json(payload)

    async def publish():
        nonlocal last_seq
        while True:
            if active_session:
                db = connect()
                try:
                    rows = db.execute("SELECT payload_json FROM discussion_events WHERE session_id=? AND event_seq>? ORDER BY event_seq", (active_session, last_seq)).fetchall()
                finally: db.close()
                for row in rows:
                    event = json.loads(row[0])
                    await send(event)
                    last_seq = event['event_seq']
            await asyncio.sleep(0.05)

    def schedule(command):
        task = asyncio.create_task(execute(command))
        tasks.add(task)
        def completed(done):
            tasks.discard(done)
            if not done.cancelled() and done.exception(): logger.error("discussion execution failed", exc_info=done.exception())
        task.add_done_callback(completed)

    publisher = asyncio.create_task(publish())
    try:
        while True:
            try:
                command = await websocket.receive_json()
                if not await check_websocket_rate_limit(websocket): return
                if not isinstance(command, dict): raise ValueError()
            except ValueError:
                await send(_protocol_error(active_session or '', "消息必须是合法 JSON 对象"))
                continue
            session_id = str(command.get("session_id", ""))
            try:
                if active_session and session_id != active_session:
                    raise AppException("WS_PROTOCOL_ERROR", "同一连接不能切换研讨会话", 400)
                immediate, should_execute = accept_command(command)
                if not active_session:
                    active_session = session_id
                    last_seq = max(0, int(command.get('last_event_seq') or 0)) if command.get('type') == 'resume' else 0
                for event in immediate:
                    if event["event_seq"] <= last_seq: await send(event)
                # All committed events, including acknowledgements, use one ordered publisher.
                if should_execute: schedule(command)
                elif command.get("type") in {"resume", "recover"}:
                    for pending in pending_commands(session_id): schedule(pending)
            except (AppException, ValueError, TypeError) as exc:
                await send({**_protocol_error(session_id, str(exc)), "error": {"code": getattr(exc, 'code', 'WS_PROTOCOL_ERROR'), "message": getattr(exc, 'message', str(exc))}})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("websocket handler crashed")
        with contextlib.suppress(Exception): await websocket.close(code=1011)
    finally:
        publisher.cancel()
        for task in tasks: task.cancel()
        await asyncio.gather(publisher, *tasks, return_exceptions=True)
