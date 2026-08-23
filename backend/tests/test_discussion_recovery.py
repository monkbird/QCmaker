import json

from backend.app.agents.discussion import ROLE_PROMPTS


def _fake_chat_factory(fail_once_roles: set[str], routed: list[str]):
    """Deterministic LLM stand-in.

    - summary prompt -> fixed JSON summary
    - routing prompt (marker arrives in the USER message) -> fixed role array
    - role prompts -> "<role>的发言"; roles in fail_once_roles fail exactly once
    """
    failed: set[str] = set()

    async def fake_chat(messages, role=None):
        system = messages[0]["content"]
        if "只输出合法JSON" in system:
            return '{"problem":"故障率偏高","root_causes":["点检不足"],"countermeasures":["完善点检"],"summary":"形成闭环"}'
        if "JSON数组" in messages[-1]["content"]:
            return json.dumps(routed)
        for agent_role, prompt in ROLE_PROMPTS.items():
            if system.startswith(prompt[:6]):
                if agent_role in fail_once_roles and agent_role not in failed:
                    failed.add(agent_role); raise RuntimeError("simulated transient llm outage")
                return f"{agent_role}的发言"
        return "发言"
    return fake_chat


def _drain(ws, count):
    return [ws.receive_json() for _ in range(count)]


def test_transient_error_is_recoverable_and_requeues(client, monkeypatch):
    from backend.app.repositories.database import connect
    from backend.app.services import discussion_session

    monkeypatch.setattr(discussion_session, "chat", _fake_chat_factory({"analyst"}, ["researcher", "analyst", "critic"]))
    with client.websocket_connect("/api/discussion/ws") as ws:
        ws.send_json({"type": "start", "session_id": "rec1", "client_message_id": "c1", "topic": "降低故障率", "data_summary": "近10月数据"})
        # exact sequence: ack(1) moderator(2) researcher(3) error(4)
        events = _drain(ws, 4)
        assert events[0]["type"] == "ack"
        assert events[-1]["type"] == "error" and events[-1]["recoverable"] is True
        agents = [event.get("agent") for event in events if event["type"] == "agent_message"]
        assert agents == ["moderator", "researcher"]

        ws.send_json({"type": "recover", "session_id": "rec1", "client_message_id": "c2"})
        # exact sequence: ack(5) analyst(6) critic(7) round_done(8)
        assert ws.receive_json()["type"] == "ack"
        recovered = _drain(ws, 3)
        assert [event["type"] for event in recovered] == ["agent_message", "agent_message", "round_done"]
        assert {event.get("agent") for event in recovered if event["type"] == "agent_message"} == {"analyst", "critic"}

    db = connect()
    try:
        history = json.loads(db.execute("SELECT state_json FROM discussion_sessions WHERE session_id='rec1'").fetchone()[0])["history"]
    finally:
        db.close()
    speakers = [item["agent"] for item in history]
    for agent_role in ("moderator", "researcher", "analyst", "critic"):
        assert speakers.count(agent_role) == 1
    assert "user" not in speakers


def test_fatal_error_keeps_terminal_state(client, monkeypatch):
    from backend.app.core.errors import AppException
    from backend.app.repositories.database import connect
    from backend.app.services import discussion_session

    async def bad_chat(_messages, role=None):
        raise AppException("WS_PROTOCOL_ERROR", "坏消息", 400)

    monkeypatch.setattr(discussion_session, "chat", bad_chat)
    with client.websocket_connect("/api/discussion/ws") as ws:
        ws.send_json({"type": "start", "session_id": "rec2", "client_message_id": "c1", "topic": "课题", "data_summary": "摘要"})
        events = _drain(ws, 2)  # ack(1) error(2)
    assert events[-1]["type"] == "error" and events[-1]["recoverable"] is False
    db = connect()
    try:
        status = db.execute("SELECT status FROM discussion_sessions WHERE session_id='rec2'").fetchone()[0]
    finally:
        db.close()
    assert status == "error"


def test_user_message_not_duplicated_across_recovery(client, monkeypatch):
    from backend.app.repositories.database import connect
    from backend.app.services import discussion_session

    monkeypatch.setattr(discussion_session, "chat", _fake_chat_factory({"critic"}, ["analyst", "critic"]))
    with client.websocket_connect("/api/discussion/ws") as ws:
        ws.send_json({"type": "start", "session_id": "rec3", "client_message_id": "c0", "topic": "课题", "data_summary": "摘要"})
        # ack(1) moderator(2) analyst(3) error(critic fails once)(4)
        events = _drain(ws, 4)
        assert events[-1]["type"] == "error"

        ws.send_json({"type": "recover", "session_id": "rec3", "client_message_id": "r1"})
        # ack(5) critic(6) round_done(7)
        assert ws.receive_json()["type"] == "ack"
        tail = _drain(ws, 2)
        assert [event["type"] for event in tail] == ["agent_message", "round_done"]
        assert tail[0]["agent"] == "critic"

        ws.send_json({"type": "message", "session_id": "rec3", "client_message_id": "m1", "content": "请补充设备台账信息"})
        # ack(8) moderator(9) analyst(10) critic(11) round_done(12)
        message_events = _drain(ws, 5)
        assert [event["type"] for event in message_events] == ["ack", "agent_message", "agent_message", "agent_message", "round_done"]

    db = connect()
    try:
        history = json.loads(db.execute("SELECT state_json FROM discussion_sessions WHERE session_id='rec3'").fetchone()[0])["history"]
    finally:
        db.close()
    user_entries = [item for item in history if item["agent"] == "user"]
    assert len(user_entries) == 1
    assert user_entries[0]["content"] == "请补充设备台账信息"
    speakers = [item["agent"] for item in history]
    assert speakers.count("moderator") == 2  # start round + message round
