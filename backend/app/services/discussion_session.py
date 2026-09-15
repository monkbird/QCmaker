from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import math
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from backend.app.agents.discussion import ROLE_PROMPTS, run_role_graph
from backend.app.core.errors import AppException
from backend.app.core.llm_gateway import chat
from backend.app.models.contracts import DiscussionSummary
from backend.app.repositories.database import connect, transaction
from backend.app.repositories.dataset_repository import _from_row, _load_row
from backend.app.services.rag import rag_service
from backend.app.services.search import search_service

logger = logging.getLogger(__name__)

_locks: dict[str, asyncio.Lock] = {}
VALID_COMMANDS = {"start", "message", "resume", "finish", "recover"}
RUNNABLE_COMMANDS = {"start", "message", "finish"}
FATAL_ERROR_CODES = {"WS_PROTOCOL_ERROR", "SESSION_NOT_FOUND"}


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
    if not session_id or not client_id or kind not in VALID_COMMANDS: raise AppException("WS_PROTOCOL_ERROR", "WS 消息字段不完整", 400)
    with transaction(immediate=True) as db:
        existing = db.execute("SELECT payload_json FROM discussion_commands WHERE session_id=? AND client_message_id=?", (session_id, client_id)).fetchone()
        if existing:
            ack = db.execute("SELECT payload_json FROM discussion_events WHERE session_id=? AND client_message_id=? AND event_type='ack'", (session_id, client_id)).fetchone()
            return ([json.loads(ack[0])] if ack else []), False
        session = db.execute("SELECT status FROM discussion_sessions WHERE session_id=?", (session_id,)).fetchone()
        if kind == "start" and not session:
            if not command.get("topic") or not command.get("dataset_id") or not command.get("project_id") or type(command.get("revision")) is not int:
                raise AppException("WS_PROTOCOL_ERROR", "start 必须携带课题、项目和已确认数据版本", 400)
            dataset = _from_row(_load_row(command["dataset_id"], db))
            if dataset.revision != command["revision"] or dataset.confirmed_revision != dataset.revision:
                raise AppException("DATA_REVISION_CONFLICT", "请确认当前数据版本后再开始研讨", 409)
            statistics = {}
            for column in dataset.columns:
                values = [row.values.get(column.name) for row in dataset.rows]
                present = [value for value in values if value is not None and value != ""]
                numeric = []
                for value in present:
                    try:
                        number = float(value)
                        if not isinstance(value, bool) and math.isfinite(number): numeric.append(number)
                    except (TypeError, ValueError): pass
                stats = {"count": len(present), "missing": len(values)-len(present)}
                if numeric and len(numeric) == len(present):
                    stats.update(min=min(numeric), max=max(numeric), sum=sum(numeric), mean=sum(numeric)/len(numeric))
                else: stats["frequencies"] = Counter(str(value)[:100] for value in present).most_common(10)
                statistics[column.name] = stats
            summary = json.dumps({"rows": len(dataset.rows), "statistics": statistics, "samples": [row.model_dump() for row in dataset.rows[:10]], "quality": {"mode": dataset.report.mode, "issues": [{"type": issue.issue_type, "column": issue.column, "affected_rows": len(issue.row_ids)} for issue in dataset.report.issues], "removed_rows": dataset.report.removed_rows, "filled_cells": dataset.report.filled_cells}}, ensure_ascii=False)
            state = {"topic": command["topic"], "dataset_id": dataset.dataset_id, "revision": dataset.revision, "project_id": command["project_id"], "data_summary": summary, "history": [], "round": 0}
            db.execute("INSERT INTO discussion_sessions VALUES(?,?,?,?,?,?,?,?)", (session_id, "created", json.dumps(state, ensure_ascii=False), 1, None, 0, None, (datetime.now(UTC) + timedelta(hours=24)).isoformat()))
        elif kind == "start" and session: raise AppException("WS_PROTOCOL_ERROR", "session_id 已存在，请使用 resume 或 recover", 400)
        elif not session: raise AppException("SESSION_NOT_FOUND", "研讨会话不存在", 404)
        elif session["status"] in {"finished", "cancelled"} and kind in {"message", "finish", "recover"}: raise AppException("WS_PROTOCOL_ERROR", "当前会话已经结束", 400)
        if session and session["status"] in {"round_error", "error"} and kind in {"message", "finish"}:
            raise AppException("WS_PROTOCOL_ERROR", "请先恢复失败轮次", 400)
        if kind == "resume":
            last = command.get("last_event_seq", 0)
            maximum = db.execute("SELECT next_event_seq-1 FROM discussion_sessions WHERE session_id=?", (session_id,)).fetchone()[0]
            if type(last) is not int or last < 0 or last > maximum:
                raise AppException("WS_PROTOCOL_ERROR", "恢复事件序号超出会话范围", 400)
        if kind == "recover":
            if session["status"] != "round_error":
                raise AppException("WS_PROTOCOL_ERROR", "当前会话无需恢复", 400)
            db.execute("UPDATE discussion_commands SET status='pending',picked_at=NULL,completed_at=NULL,error_json=NULL WHERE session_id=? AND status='failed'", (session_id,))
            db.execute("UPDATE discussion_sessions SET status='round_done' WHERE session_id=? AND status IN ('round_error','error')", (session_id,))
        db.execute("INSERT INTO discussion_commands VALUES(?,?,?,?,?,?,?)", (session_id, client_id, json.dumps(command, ensure_ascii=False), "pending", None, None, None))
        ack = _event(db, session_id, client_id, "ack", {"reply_to_client_message_id": client_id, "session_status": db.execute("SELECT status FROM discussion_sessions WHERE session_id=?", (session_id,)).fetchone()[0]})
        if kind == "resume":
            last = int(command.get("last_event_seq") or 0); rows = db.execute("SELECT payload_json FROM discussion_events WHERE session_id=? AND event_seq>? ORDER BY event_seq", (session_id, last)).fetchall()
            db.execute("UPDATE discussion_commands SET status='completed',completed_at=? WHERE session_id=? AND client_message_id=?", (_now(), session_id, client_id))
            return [json.loads(row[0]) for row in rows], False
        if kind == "recover":
            db.execute("UPDATE discussion_commands SET status='completed',completed_at=? WHERE session_id=? AND client_message_id=?", (_now(), session_id, client_id))
            return [ack], False
    return [ack], True


async def _acquire_lease(session_id: str, client_id: str) -> tuple[str, int] | None:
    owner = f"worker_{uuid4().hex}"
    for _ in range(600):
        with transaction(immediate=True) as db:
            claim = db.execute("SELECT status FROM discussion_commands WHERE session_id=? AND client_message_id=?", (session_id, client_id)).fetchone()
            if not claim or claim["status"] not in {"pending", "running"}: return None
            terminal = db.execute("SELECT status FROM discussion_sessions WHERE session_id=?", (session_id,)).fetchone()
            if terminal and terminal["status"] in {"finished", "cancelled"}:
                db.execute("UPDATE discussion_commands SET status='completed',completed_at=? WHERE session_id=? AND client_message_id=?", (_now(), session_id, client_id))
                return None
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
    return [json.loads(row[0]) for row in rows if json.loads(row[0]).get("type") in RUNNABLE_COMMANDS]


def admin_cancel(db, session_id: str) -> dict[str, Any]:
    """Caller owns the immediate transaction and its audit record."""
    row = db.execute("SELECT status FROM discussion_sessions WHERE session_id=?", (session_id,)).fetchone()
    if not row:
        raise AppException("SESSION_NOT_FOUND", "研讨会话不存在", 404)
    if row["status"] in {"finished", "cancelled"}:
        raise AppException("SESSION_TERMINAL", "会话已结束", 409)
    db.execute("UPDATE discussion_sessions SET status='cancelled',lease_generation=lease_generation+1,lease_owner=NULL,lease_until=NULL WHERE session_id=?", (session_id,))
    count = db.execute("UPDATE discussion_commands SET status='cancelled',completed_at=? WHERE session_id=? AND status IN ('pending','running','failed')", (_now(), session_id)).rowcount
    _event(db, session_id, None, "cancelled", {"session_status": "cancelled", "reason": "admin_cancelled"})
    return {"session_id": session_id, "status": "cancelled", "cancelled_commands": count, "inflight_cost_preserved": True}


def admin_recover(db, session_id: str) -> list[dict[str, Any]]:
    row = db.execute("SELECT status,lease_until FROM discussion_sessions WHERE session_id=?", (session_id,)).fetchone()
    if not row:
        raise AppException("SESSION_NOT_FOUND", "研讨会话不存在", 404)
    if row["status"] in {"finished", "cancelled"}:
        raise AppException("SESSION_TERMINAL", "会话已结束", 409)
    if row["lease_until"] and datetime.fromisoformat(row["lease_until"]) > datetime.now(UTC):
        raise AppException("SESSION_IN_USE", "执行租约尚未过期", 409)
    rows = db.execute("SELECT payload_json FROM discussion_commands WHERE session_id=? AND status IN ('pending','running','failed') ORDER BY rowid", (session_id,)).fetchall()
    commands = [json.loads(row[0]) for row in rows if json.loads(row[0]).get("type") in RUNNABLE_COMMANDS]
    if not commands:
        raise AppException("SESSION_NOT_RECOVERABLE", "会话没有可恢复的命令", 409)
    db.execute("UPDATE discussion_sessions SET status='round_done',lease_generation=lease_generation+1,lease_owner=NULL,lease_until=NULL WHERE session_id=?", (session_id,))
    for command in commands:
        db.execute("UPDATE discussion_commands SET status='pending',picked_at=NULL,completed_at=NULL,error_json=NULL WHERE session_id=? AND client_message_id=?", (session_id, command["client_message_id"]))
    _event(db, session_id, None, "recovery_requested", {"session_status": "round_done", "queued_commands": len(commands)})
    return commands


async def run_admin_recovery(commands: list[dict[str, Any]]) -> None:
    for command in commands:
        await execute(command)
        with transaction() as db:
            row = db.execute("SELECT status FROM discussion_commands WHERE session_id=? AND client_message_id=?", (command['session_id'], command['client_message_id'])).fetchone()
        if not row or row['status'] != 'completed':
            raise AppException('RECOVERY_INCOMPLETE', '恢复命令未完成，请查看会话状态与事件', 409)


async def _route_roles(context: str, start: bool) -> list[str]:
    allowed = ["researcher", "analyst", "critic"]
    prompt = "根据研讨历史选择本轮还需要发言的角色，只输出JSON数组，可选 researcher、analyst、critic，最多3个，不得重复。"
    try:
        raw = await chat([{"role": "system", "content": ROLE_PROMPTS["moderator"]}, {"role": "user", "content": prompt + "\n" + context}], role="moderator")
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```")); roles = [role for role in parsed if role in allowed]
        if roles: return list(dict.fromkeys(roles))[:3]
    except Exception: logger.warning("role routing failed; using fallback roles", exc_info=True)
    return allowed if start else ["analyst", "critic"]


async def _research_context(topic: str, project_id: str) -> str:
    snippets: list[str] = []
    try:
        documents = await rag_service.search(topic, 3, project_id); snippets.extend(document.page_content[:500] for document in documents)
    except Exception: logger.info("rag search unavailable during research context", exc_info=True)
    try:
        results = await search_service.search(topic, 3); snippets.extend(str(item.get("content", ""))[:500] for item in results)
    except Exception: logger.info("web search unavailable during research context", exc_info=True)
    return "\n可用检索资料：\n" + "\n".join(snippets) if snippets else "\n当前无可用检索资料，请明确证据边界。"


def _get_lock(session_id: str) -> asyncio.Lock:
    if len(_locks) > 256:
        for key in [k for k, v in _locks.items() if not v.locked() and k != session_id]:
            _locks.pop(key, None)
    return _locks.setdefault(session_id, asyncio.Lock())


async def execute(command: dict[str, Any]) -> list[dict[str, Any]]:
    session_id = command["session_id"]; client_id = command["client_message_id"]
    lock = _get_lock(session_id)
    async with lock:
        outputs = await _execute_locked(command, session_id, client_id)
    return outputs


async def _execute_locked(command: dict[str, Any], session_id: str, client_id: str) -> list[dict[str, Any]]:
        acquired = await _acquire_lease(session_id, client_id)
        if acquired is None: return []
        owner, generation = acquired; lease = (owner, generation); stopped = asyncio.Event(); heartbeat = asyncio.create_task(_heartbeat(session_id, owner, generation, stopped))
        db = connect()
        try:
            row = db.execute("SELECT s.state_json,c.payload_json FROM discussion_sessions s JOIN discussion_commands c ON c.session_id=s.session_id WHERE s.session_id=? AND c.client_message_id=?", (session_id, client_id)).fetchone()
        finally: db.close()
        if row is None: raise AppException("SESSION_NOT_FOUND", "研讨命令不存在", 404)
        state = json.loads(row[0]); persisted_command = json.loads(row[1])
        completed_roles = set(persisted_command.get("_completed_roles", []))

        def persist_meta(tx, *, include_state: bool = True) -> None:
            _guard_lease(tx, session_id, *lease)
            if include_state: tx.execute("UPDATE discussion_sessions SET state_json=? WHERE session_id=?", (json.dumps(state, ensure_ascii=False), session_id))
            tx.execute("UPDATE discussion_commands SET payload_json=? WHERE session_id=? AND client_message_id=?", (json.dumps(persisted_command, ensure_ascii=False), session_id, client_id))

        outputs: list[dict[str, Any]] = []
        kind = command["type"]
        # A final report must retain early confirmations and corrections. Send the
        # complete transcript in one call; provider limits surface as recoverable
        # errors instead of silently dropping evidence or adding summary calls.
        history = state['history'] if kind == "finish" else state['history'][-12:]
        context = f"课题：{state['topic']}\n数据摘要：{state['data_summary']}\n历史：{json.dumps(history, ensure_ascii=False)}"
        try:
            if kind == "message" and not persisted_command.get("_user_appended"):
                state["history"].append({"agent": "user", "content": command.get("content", "")}); persisted_command["_user_appended"] = True
                context = f"课题：{state['topic']}\n数据摘要：{state['data_summary']}\n历史：{json.dumps(state['history'][-12:], ensure_ascii=False)}"
                with transaction(immediate=True) as tx: persist_meta(tx)

            routed: list[str] = [str(role) for role in persisted_command.get("_routed_roles", [])]
            if kind != "finish":
                if "moderator" not in completed_roles:
                    content = await chat([{"role": "system", "content": ROLE_PROMPTS["moderator"]}, {"role": "user", "content": context}], role="moderator"); state["history"].append({"agent": "moderator", "content": content}); context += f"\nmoderator: {content}"; completed_roles.add("moderator"); persisted_command["_completed_roles"] = list(completed_roles)
                    with transaction(immediate=True) as tx:
                        outputs.append(_event(tx, session_id, client_id, "agent_message", {"reply_to_client_message_id": client_id, "agent": "moderator", "content": content}, lease)); persist_meta(tx)
                    routed = await _route_roles(context, kind == "start")
                elif not routed:
                    routed = await _route_roles(context, False)
                else:
                    routed = [role for role in routed if role not in completed_roles]
                persisted_command["_routed_roles"] = routed
                with transaction(immediate=True) as tx: persist_meta(tx, include_state=False)

            async def run_role(role_name: str) -> None:
                nonlocal context
                if role_name in completed_roles: return
                with transaction() as tx: _guard_lease(tx, session_id, *lease)
                role_context = context + (await _research_context(state["topic"], state["project_id"]) if role_name == "researcher" else "")
                with transaction() as tx: _guard_lease(tx, session_id, *lease)
                content = await chat([{"role": "system", "content": ROLE_PROMPTS[role_name]}, {"role": "user", "content": role_context}], role=role_name); state["history"].append({"agent": role_name, "content": content}); context += f"\n{role_name}: {content}"
                completed_roles.add(role_name); persisted_command["_completed_roles"] = list(completed_roles)
                with transaction(immediate=True) as tx:
                    outputs.append(_event(tx, session_id, client_id, "agent_message", {"reply_to_client_message_id": client_id, "agent": role_name, "content": content}, lease)); persist_meta(tx)
            await run_role_graph(routed, run_role)

            if not persisted_command.get("_round_counted"):
                state["round"] += 1; persisted_command["_round_counted"] = True
            if kind == "finish":
                with transaction() as tx: _guard_lease(tx, session_id, *lease)
                prompt = f"请把以下QC研讨整理为严格JSON，字段为 problem(string), root_causes(string[]), countermeasures(string[]), summary(string)。不要Markdown。\n{context}"
                raw = await chat([{"role": "system", "content": ROLE_PROMPTS["writer"] + "只输出合法JSON。"}, {"role": "user", "content": prompt}], role="writer")
                try:
                    summary = DiscussionSummary.model_validate(json.loads(raw.strip().removeprefix("```json").removesuffix("```")), strict=True)
                    if not summary.problem.strip() or not summary.summary.strip() or any(not item.strip() for item in [*summary.root_causes, *summary.countermeasures]):
                        raise ValueError("Summary contains blank text")
                except ValueError as exc:
                    raise AppException("DISCUSSION_SUMMARY_INVALID", "总结生成失败：模型未返回有效的结构化成果，请恢复后重试。研讨记录已保留。", 502) from exc
                with transaction(immediate=True) as tx:
                    outputs.append(_event(tx, session_id, client_id, "finished", {"reply_to_client_message_id": client_id, "summary": summary.model_dump()}, lease)); tx.execute("UPDATE discussion_sessions SET status='finished',state_json=? WHERE session_id=?", (json.dumps(state, ensure_ascii=False), session_id))
                    tx.execute("UPDATE discussion_commands SET status='completed',completed_at=? WHERE session_id=? AND client_message_id=?", (_now(), session_id, client_id))
            else:
                with transaction(immediate=True) as tx:
                    outputs.append(_event(tx, session_id, client_id, "round_done", {"reply_to_client_message_id": client_id, "round": state["round"]}, lease)); tx.execute("UPDATE discussion_sessions SET status='round_done',state_json=? WHERE session_id=?", (json.dumps(state, ensure_ascii=False), session_id))
                    _guard_lease(tx, session_id, *lease); tx.execute("UPDATE discussion_commands SET status='completed',completed_at=? WHERE session_id=? AND client_message_id=?", (_now(), session_id, client_id))
        except Exception as exc:
            code = getattr(exc, "code", None) or "INTERNAL_ERROR"
            if code == "SESSION_LEASE_LOST":
                logger.warning("lease lost while executing %s/%s; another worker took over", session_id, client_id)
            else:
                fatal = code in FATAL_ERROR_CODES
                try:
                    with transaction(immediate=True) as tx:
                        outputs.append(_event(tx, session_id, client_id, "error", {"reply_to_client_message_id": client_id, "error": {"code": code, "message": str(exc)}, "recoverable": not fatal}, lease)); tx.execute("UPDATE discussion_sessions SET status=?,state_json=? WHERE session_id=?", ("error" if fatal else "round_error", json.dumps(state, ensure_ascii=False), session_id)); tx.execute("UPDATE discussion_commands SET status='failed',error_json=? WHERE session_id=? AND client_message_id=?", (json.dumps({"code": code, "message": str(exc)}), session_id, client_id))
                        persist_meta(tx, include_state=False)
                except AppException as inner:
                    if getattr(inner, "code", None) != "SESSION_LEASE_LOST": logger.exception("failed to persist error event for %s/%s", session_id, client_id)
        finally:
            stopped.set(); heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError): await heartbeat
            with transaction(immediate=True) as tx: tx.execute("UPDATE discussion_sessions SET lease_owner=NULL,lease_until=NULL WHERE session_id=? AND lease_owner=? AND lease_generation=?", (session_id, owner, generation))
        return outputs
