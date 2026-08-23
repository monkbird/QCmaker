import contextlib
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.core.errors import AppException
from backend.app.core.security import verify_websocket_token
from backend.app.services.discussion_session import accept_command, execute, pending_commands

logger = logging.getLogger(__name__)

router = APIRouter()


def _protocol_error(session_id: str, message: str) -> dict:
    return {"type": "error", "session_id": session_id, "event_seq": 0, "timestamp": "", "error": {"code": "WS_PROTOCOL_ERROR", "message": message}, "recoverable": False}


async def _safe_send(websocket: WebSocket, payload: dict) -> bool:
    try:
        await websocket.send_json(payload); return True
    except (WebSocketDisconnect, RuntimeError):
        return False


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    if not await verify_websocket_token(websocket): return
    try:
        while True:
            try:
                command = await websocket.receive_json()
            except ValueError:
                if not await _safe_send(websocket, _protocol_error("", "消息不是合法 JSON")): return
                continue
            session_id = str(command.get("session_id", ""))
            try:
                immediate, should_execute = accept_command(command)
                for event in immediate:
                    if not await _safe_send(websocket, event): return
                if should_execute:
                    for event in await execute(command):
                        if not await _safe_send(websocket, event): return
                elif command.get("type") in {"resume", "recover"}:
                    for pending in pending_commands(session_id):
                        for event in await execute(pending):
                            if not await _safe_send(websocket, event): return
            except AppException as exc:
                if not await _safe_send(websocket, {**_protocol_error(session_id, exc.message), "error": {"code": exc.code, "message": exc.message}}): return
    except WebSocketDisconnect:
        return
    except Exception:
        logger.exception("websocket handler crashed")
        with contextlib.suppress(Exception):
            await websocket.close(code=1011)
