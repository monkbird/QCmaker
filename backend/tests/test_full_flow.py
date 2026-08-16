from io import BytesIO


def test_offline_full_flow(client, monkeypatch):
    from backend.app.api.endpoints import topic as topic_endpoint
    from backend.app.services import discussion_session

    async def fake_chat(messages):
        if "只输出合法JSON" in messages[0]["content"]:
            return '{"problem":"波动偏大","root_causes":["点检不足"],"countermeasures":["完善点检"],"summary":"闭环改进"}'
        return "降低设备故障率"

    monkeypatch.setattr(topic_endpoint, "chat", fake_chat)
    monkeypatch.setattr(discussion_session, "chat", fake_chat)
    assert client.get("/api/config/").status_code == 200
    topic = client.post("/api/topic/chat", json={"message": "设备故障多", "history": []}).json()["response"]
    upload = client.post("/api/data/upload", files={"file": ("data.csv", BytesIO("月份,故障数\n1月,4\n2月,2\n".encode()), "text/csv")}).json()
    confirmed = client.post("/api/data/confirm", json={"dataset_id": upload["dataset_id"], "revision": 0}).json()
    with client.websocket_connect("/api/discussion/ws") as ws:
        ws.send_json({"type": "start", "session_id": "flow", "client_message_id": "start", "topic": topic, "data_summary": "2行月度数据"})
        for _ in range(6): ws.receive_json()
        ws.send_json({"type": "finish", "session_id": "flow", "client_message_id": "finish"})
        ws.receive_json(); summary = ws.receive_json()["summary"]
    chart = client.post("/api/visualization/generate", json={"chart_type": "line", "dataset_id": confirmed["dataset_id"], "revision": 0, "x_axis": "月份", "y_axis": "故障数"})
    assert chart.status_code == 200
    ppt = client.post("/api/ppt/generate", json={"project_name": "QC项目", "topic": topic, "data_summary": "2行月度数据", "discussion_summary": summary, "chart_images": []})
    assert ppt.status_code == 200
    assert client.get(f"/api/ppt/download/{ppt.json()['file_id']}").status_code == 200
