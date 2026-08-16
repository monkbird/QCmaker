from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from backend.app.agents.discussion import ROLE_PROMPTS, run_role_graph
from backend.app.core.errors import AppException
from backend.app.core.llm_gateway import chat
from backend.app.models.contracts import DiscussionSummary
from backend.app.repositories.database import connect, transaction
from backend.app.services.rag import rag_service
from backend.app.services.search import search_service

_locks: dict[str, asyncio.Lock] = {}


def _now() -> str: return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _guard_lease(db, session_id: str, owner: str, generation: int) -> None:
    row = db.execute("SELECT lease_owner,lease_generation,lease_until FROM discussion_sessions WHERE session_id=?", (session_id,)).fetchone()
    if not row or row["lease_owner"] != owner or row["lease_generation"] != generation or not row["lease_until"] or datetime.fromisoformat(row["lease_until"]) <= datetime.now(UTC):
        raise AppException("SESSION_LEASE_LOST", "研讨执行租约已失效", 409)


def _event(db, session_id: str, client_id: str | None, event_type: str, payload: dict[str, Any], lease: tuple[str, int] | None = None) -> dict[str, Any]:
    if lease: _guard_lease(db, session_id, *lease)
    row = db.execute("SELECT next_event_seq FROM discussion_sessions WHERE session_id=?", (session_id,)).fetchone()
    if not row: raise AppException("SESSION_NOT_FOUND", "研讨会话不存在", 404)
    seq = row[0]; body = {"type": event_type, "session_id": session_id, "event_seq": seq, "timestamp": _now(), **payload}
    db.execute("INSERT INTO discussion_events VALUES(?,?,?,?,?,?)", (session_id, seq, client_id, event_type, json.dumps(body, ensure_ascii=False), _now()))
    db.execute("UPDATE discussion_sessions SET next_event_seq=? WHERE session_id=?", (seq + 1, session_id)); return body


def accept_command(command: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    session_id = str(command.get("session_id", "")); client_id = str(command.get("client_message_id", "")); kind = command.get("type")
    if not session_id or not client_id or kind not in {"start", "message", "resume", "finish"}: raise AppException("WS_PROTOCOL_ERROR", "WS 消息字段不完整", 400)
    with transaction(immediate=True) as db:
        existing = db.execute("SELECT payload_json FROM discussion_commands WHERE session_id=? AND client_message_id=?", (session_id, client_id)).fetchone()
        if existing:
            ack = db.execute("SELECT payload_json FROM discussion_events WHERE session_id=? AND client_message_id=? AND event_type='ack'", (session_id, client_id)).fetchone()
            return ([json.loads(ack[0])] if ack else []), False
        session = db.execute("SELECT status FROM discussion_sessions WHERE session_id=?", (session_id,)).fetchone()
        if kind == "start" and not session:
            if not command.get("topic") or not command.get("data_summary"): raise AppException("WS_PROTOCOL_ERROR", "start 必须携带 topic 和 data_summary", 400)
            state = {"topic": command["topic"], "data_summary": command["data_summary"], "history": [], "round": 0}
            db.execute("INSERT INTO discussion_sessions VALUES(?,?,?,?,?,?,?,?)", (session_id, "created", json.dumps(state, ensure_ascii=False), 1, None, 0, None, (datetime.now(UTC) + timedelta(hours=24)).isoformat()))
        elif kind == "start" and session: raise AppException("WS_PROTOCOL_ERROR", "session_id 已存在，请使用 resume", 400)
        elif not session: raise AppException("SESSION_NOT_FOUND", "研讨会话不存在", 404)
        elif session["status"] in {"finished", "error"} and kind in {"message", "finish"}: raise AppException("WS_PROTOCOL_ERROR", "当前会话已经结束", 400)
        db.execute("INSERT INTO discussion_commands VALUES(?,?,?,?,?,?,?)", (session_id, client_id, json.dumps(command, ensure_ascii=False), "pending", None, None, None))
        ack = _event(db, session_id, client_id, "ack", {"reply_to_client_message_id": client_id})
        if kind == "resume":
            last = int(command.get("last_event_seq") or 0); rows = db.execute("SELECT payload_json FROM discussion_events WHERE session_id=? AND event_seq>? ORDER BY event_seq", (session_id, last)).fetchall()
            db.execute("UPDATE discussion_commands SET status='completed',completed_at=? WHERE session_id=? AND client_message_id=?", (_now(), session_id, client_id))
            return [json.loads(row[0]) for row in rows], False
    return [ack], True


async def _acquire_lease(session_id: str, client_id: str) -> tuple[str, int]:
    owner = f"worker_{uuid4().hex}"
    for _ in range(600):
        with transaction(immediate=True) as db:
            row = db.execute("SELECT lease_owner,lease_generation,lease_until FROM discussion_sessions WHERE session_id=?", (session_id,)).fetchone()
            if not row: raise AppException("SESSION_NOT_FOUND", "研讨会话不存在", 404)
            expired = not row["lease_until"] or datetime.fromisoformat(row["lease_until"]) <= datetime.now(UTC)
            if not row["lease_owner"] or expired:
                generation = int(row["lease_generation"]) + 1; until = datetime.now(UTC) + timedelta(seconds=30)
                db.execute("UPDATE discussion_sessions SET lease_owner=?,lease_generation=?,lease_until=? WHERE session_id=?", (owner, generation, until.isoformat(), session_id))
                db.execute("UPDATE discussion_commands SET status='running',picked_at=? WHERE session_id=? AND client_message_id=? AND status IN ('pending','running')", (_now(), session_id, client_id))
                return owner, generation
        await asyncio.sleep(0.1)
    raise AppException("SESSION_LEASE_LOST", "研讨会话正由其他工作进程执行", 409)


async def _heartbeat(session_id: str, owner: str, generation: int, stopped: asyncio.Event) -> None:
    while not stopped.is_set():
        try: await asyncio.wait_for(stopped.wait(), timeout=10)
        except TimeoutError:
            with transaction(immediate=True) as db:
                cursor = db.execute("UPDATE discussion_sessions SET lease_until=? WHERE session_id=? AND lease_owner=? AND lease_generation=?", ((datetime.now(UTC) + timedelta(seconds=30)).isoformat(), session_id, owner, generation))
                if cursor.rowcount == 0: return


def pending_commands(session_id: str) -> list[dict[str, Any]]:
    db = connect()
    try: rows = db.execute("SELECT payload_json FROM discussion_commands WHERE session_id=? AND status IN ('pending','running') ORDER BY rowid", (session_id,)).fetchall()
    finally: db.close()
    return [json.loads(row[0]) for row in rows if json.loads(row[0]).get("type") != "resume"]


async def _route_roles(context: str, start: bool) -> list[str]:
    allowed = ["researcher", "analyst", "critic"]
    prompt = "根据研讨历史选择本轮还需要发言的角色，只输出JSON数组，可选 researcher、analyst、critic，最多3个，不得重复。"
    try:
        raw = await chat([{"role": "system", "content": ROLE_PROMPTS["moderator"]}, {"role": "user", "content": prompt + "\n" + context}])
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```")); roles = [role for role in parsed if role in allowed]
        if roles: return list(dict.fromkeys(roles))[:3]
    except Exception: pass
    return allowed if start else ["analyst", "critic"]


async def _research_context(topic: str) -> str:
    snippets: list[str] = []
    try:
        documents = await rag_service.search(topic, 3); snippets.extend(document.page_content[:500] for document in documents)
    except Exception: pass
    try:
        results = await search_service.search(topic, 3); snippets.extend(str(item.get("content", ""))[:500] for item in results)
    except Exception: pass
    return "\n可用检索资料：\n" + "\n".join(snippets) if snippets else "\n当前无可用检索资料，请明确证据边界。"


async def execute(command: dict[str, Any]) -> list[dict[str, Any]]:
    session_id = command["session_id"]; client_id = command["client_message_id"]
    async with _locks.setdefault(session_id, asyncio.Lock()):
        owner, generation = await _acquire_lease(session_id, client_id); lease = (owner, generation); stopped = asyncio.Event(); heartbeat = asyncio.create_task(_heartbeat(session_id, owner, generation, stopped))
        db = connect()
        try:
            row = db.execute("SELECT s.state_json,c.payload_json FROM discussion_sessions s JOIN discussion_commands c ON c.session_id=s.session_id WHERE s.session_id=? AND c.client_message_id=?", (session_id, client_id)).fetchone(); state = json.loads(row[0]); persisted_command = json.loads(row[1]); completed_roles = set(persisted_command.get("_completed_roles", []))
        finally: db.close()
        if command["type"] == "message": state["history"].append({"agent": "user", "content": command.get("content", "")})
        outputs: list[dict[str, Any]] = []
        roles = ["moderator"]
        if command["type"] == "finish": roles = []
        context = f"课题：{state['topic']}\n数据摘要：{state['data_summary']}\n历史：{json.dumps(state['history'][-12:], ensure_ascii=False)}"
        try:
            routed: list[str] = []
            if roles:
                moderator = roles[0]; routed = await _route_roles(context, command["type"] == "start") if moderator in completed_roles else []
                if moderator not in completed_roles:
                    role_context = context
                    content = await chat([{"role": "system", "content": ROLE_PROMPTS[moderator]}, {"role": "user", "content": role_context}]); state["history"].append({"agent": moderator, "content": content}); context += f"\n{moderator}: {content}"; completed_roles.add(moderator); persisted_command["_completed_roles"] = list(completed_roles)
                    with transaction(immediate=True) as tx:
                        outputs.append(_event(tx, session_id, client_id, "agent_message", {"reply_to_client_message_id": client_id, "agent": moderator, "content": content}, lease)); tx.execute("UPDATE discussion_sessions SET state_json=? WHERE session_id=?", (json.dumps(state, ensure_ascii=False), session_id)); tx.execute("UPDATE discussion_commands SET payload_json=? WHERE session_id=? AND client_message_id=?", (json.dumps(persisted_command, ensure_ascii=False), session_id, client_id))
                    routed = await _route_roles(context, command["type"] == "start")

            async def run_role(role: str) -> None:
                nonlocal context
                if role in completed_roles: return
                role_context = context + (await _research_context(state["topic"]) if role == "researcher" else "")
                content = await chat([{"role": "system", "content": ROLE_PROMPTS[role]}, {"role": "user", "content": role_context}]); state["history"].append({"agent": role, "content": content}); context += f"\n{role}: {content}"
                completed_roles.add(role); persisted_command["_completed_roles"] = list(completed_roles)
                with transaction(immediate=True) as tx:
                    outputs.append(_event(tx, session_id, client_id, "agent_message", {"reply_to_client_message_id": client_id, "agent": role, "content": content}, lease)); tx.execute("UPDATE discussion_sessions SET state_json=? WHERE session_id=?", (json.dumps(state, ensure_ascii=False), session_id)); tx.execute("UPDATE discussion_commands SET payload_json=? WHERE session_id=? AND client_message_id=?", (json.dumps(persisted_command, ensure_ascii=False), session_id, client_id))
            await run_role_graph(routed, run_role)
            state["round"] += 1
            if command["type"] == "finish":
                prompt = f"请把以下QC研讨整理为严格JSON，字段为 problem(string), root_causes(string[]), countermeasures(string[]), summary(string)。不要Markdown。\n{context}"
                raw = await chat([{"role": "system", "content": ROLE_PROMPTS["writer"] + "只输出合法JSON。"}, {"role": "user", "content": prompt}])
                try: summary = DiscussionSummary.model_validate(json.loads(raw.strip().removeprefix("```json").removesuffix("```")))
                except Exception: summary = DiscussionSummary(problem=state["topic"], root_causes=[item["content"] for item in state["history"] if item["agent"] == "critic"][-3:], countermeasures=["根据研讨意见制定责任明确、节点清晰的改进措施"], summary=raw)
                with transaction(immediate=True) as tx:
                    outputs.append(_event(tx, session_id, client_id, "finished", {"reply_to_client_message_id": client_id, "summary": summary.model_dump()}, lease)); tx.execute("UPDATE discussion_sessions SET status='finished',state_json=? WHERE session_id=?", (json.dumps(state, ensure_ascii=False), session_id))
            else:
                with transaction(immediate=True) as tx:
                    outputs.append(_event(tx, session_id, client_id, "round_done", {"reply_to_client_message_id": client_id, "round": state["round"]}, lease)); tx.execute("UPDATE discussion_sessions SET status='round_done',state_json=? WHERE session_id=?", (json.dumps(state, ensure_ascii=False), session_id))
            with transaction(immediate=True) as tx:
                _guard_lease(tx, session_id, *lease); tx.execute("UPDATE discussion_commands SET status='completed',completed_at=? WHERE session_id=? AND client_message_id=?", (_now(), session_id, client_id))
        except Exception as exc:
            if getattr(exc, "code", None) != "SESSION_LEASE_LOST":
                with transaction(immediate=True) as tx:
                    outputs.append(_event(tx, session_id, client_id, "error", {"reply_to_client_message_id": client_id, "error": {"code": getattr(exc, "code", "INTERNAL_ERROR"), "message": str(exc)}, "recoverable": False}, lease)); tx.execute("UPDATE discussion_sessions SET status='error' WHERE session_id=?", (session_id,)); tx.execute("UPDATE discussion_commands SET status='failed',error_json=? WHERE session_id=? AND client_message_id=?", (json.dumps({"message": str(exc)}), session_id, client_id))
        finally:
            stopped.set(); heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError): await heartbeat
            with transaction(immediate=True) as tx: tx.execute("UPDATE discussion_sessions SET lease_owner=NULL,lease_until=NULL WHERE session_id=? AND lease_owner=? AND lease_generation=?", (session_id, owner, generation))
        return outputs
