def test_ws_session_finish_and_resume(client, monkeypatch):
    from backend.app.services import discussion_session

    async def fake_chat(messages):
        if "只输出合法JSON" in messages[0]["content"]:
            return '{"problem":"故障率偏高","root_causes":["点检不足"],"countermeasures":["完善点检"],"summary":"形成闭环"}'
        return f"发言：{messages[0]['content'][:8]}"

    monkeypatch.setattr(discussion_session, "chat", fake_chat)
    with client.websocket_connect("/api/discussion/ws") as ws:
        ws.send_json({"type": "start", "session_id": "s1", "client_message_id": "c1", "topic": "降低故障率", "data_summary": "共10行"})
        events = [ws.receive_json() for _ in range(6)]
        assert [event["event_seq"] for event in events] == list(range(1, 7))
        assert events[-1]["type"] == "round_done"
        ws.send_json({"type": "finish", "session_id": "s1", "client_message_id": "c2"})
        ack = ws.receive_json(); finished = ws.receive_json()
        assert ack["type"] == "ack" and finished["type"] == "finished"
        assert finished["summary"]["countermeasures"] == ["完善点检"]
    with client.websocket_connect("/api/discussion/ws") as ws:
        ws.send_json({"type": "resume", "session_id": "s1", "client_message_id": "c3", "last_event_seq": 6})
        replay = [ws.receive_json() for _ in range(3)]
        assert [event["event_seq"] for event in replay] == [7, 8, 9]


def test_ws_deduplicates_client_message(client, monkeypatch):
    from backend.app.services import discussion_session
    calls = 0

    async def fake_chat(_):
        nonlocal calls; calls += 1; return "ok"

    monkeypatch.setattr(discussion_session, "chat", fake_chat)
    command = {"type": "start", "session_id": "s2", "client_message_id": "same", "topic": "课题", "data_summary": "摘要"}
    with client.websocket_connect("/api/discussion/ws") as ws:
        ws.send_json(command)
        for _ in range(6): ws.receive_json()
        ws.send_json(command)
        assert ws.receive_json()["type"] == "ack"
    assert calls == 5
