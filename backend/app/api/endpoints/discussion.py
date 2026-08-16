from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.core.errors import AppException
from backend.app.services.discussion_session import accept_command, execute, pending_commands

router = APIRouter()

@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            command = await websocket.receive_json()
            try:
                immediate, should_execute = accept_command(command)
                for event in immediate: await websocket.send_json(event)
                if should_execute:
                    for event in await execute(command): await websocket.send_json(event)
                elif command.get("type") == "resume":
                    for pending in pending_commands(command.get("session_id", "")):
                        for event in await execute(pending): await websocket.send_json(event)
            except AppException as exc:
                await websocket.send_json({"type": "error", "session_id": command.get("session_id", ""), "event_seq": 0, "timestamp": "", "error": {"code": exc.code, "message": exc.message}, "recoverable": False})
    except WebSocketDisconnect:
        return
