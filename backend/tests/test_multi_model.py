import json

import pytest


def _give_main_key(isolated_settings):
    isolated_settings.OPENAI_API_KEY = "sk-main"
    return isolated_settings


def test_role_resolution_falls_back_to_main_model(client, isolated_settings):
    from backend.app.services.model_roles import resolve_role_target
    _give_main_key(isolated_settings)
    target = resolve_role_target("critic")
    assert target.provider == "openai" and target.model == "gpt-4o-mini"


def test_mapped_role_uses_provider_credentials(client, isolated_settings):
    from backend.app.services.model_roles import resolve_role_target

    isolated_settings.OPENAI_API_KEY = "sk-main"
    isolated_settings.PROVIDER_CREDENTIALS = json.dumps({"deepseek": {"api_key": "sk-ds"}})
    isolated_settings.ROLE_MODELS = json.dumps({"critic": "deepseek|deepseek-v4-pro"})
    target = resolve_role_target("critic")
    assert target.provider == "deepseek" and target.model == "deepseek-v4-pro" and target.api_key == "sk-ds"
    assert resolve_role_target("moderator").provider == "openai"


def test_mapped_role_without_saved_key_is_rejected(client, isolated_settings):
    from backend.app.core.errors import AppException
    from backend.app.services.model_roles import resolve_role_target

    isolated_settings.OPENAI_API_KEY = "sk-main"
    isolated_settings.ROLE_MODELS = json.dumps({"analyst": "moonshot|kimi-k2.5"})
    with pytest.raises(AppException) as exc:
        resolve_role_target("analyst")
    assert exc.value.code == "ROLE_MODEL_KEY_MISSING"


def test_config_update_saves_role_models_and_credentials(client):
    from backend.app.core import config as core_config
    core_config.get_settings().OPENAI_API_KEY = "sk-main"

    bad = client.post("/api/config/update", json={"role_models": {"hacker": "x|y"}})
    assert bad.status_code == 400 and bad.json()["code"] == "CONFIG_INVALID"

    unknown = client.post("/api/config/update", json={"role_models": {"critic": "nosuch|model"}})
    assert unknown.status_code == 404 and unknown.json()["code"] == "PROVIDER_NOT_FOUND"

    ok = client.post("/api/config/update", json={
        "role_models": {"critic": "deepseek|deepseek-v4-pro"},
        "provider_credentials": {"deepseek": {"api_key": "sk-ds-1"}},
    })
    assert ok.status_code == 200
    payload = ok.json()
    assert payload["role_models"]["critic"] == "deepseek|deepseek-v4-pro"
    assert payload["credential_providers"] == ["deepseek"]
    assert "sk-ds-1" not in json.dumps(payload)


async def _empty_rag(_query, _k):
    return []


def test_topic_evaluate_returns_scores_and_references(client, monkeypatch):
    from backend.app.api.endpoints import topic as topic_endpoint
    captured = {}

    async def fake_chat(messages, role=None):
        captured["role"] = role; captured["prompt"] = messages[-1]["content"]
        return '{"specific":5,"measurable":3,"achievable":4,"relevant":5,"time_bound":2,"verdict":"基本可行","suggestions":["补充目标值"]}'

    async def fake_rag_search(_query, _k):
        class Doc:
            page_content = "历史课题：降低设备故障率"
        return [Doc()]

    monkeypatch.setattr(topic_endpoint, "chat", fake_chat)
    monkeypatch.setattr(topic_endpoint.rag_service, "search", fake_rag_search)
    result = client.post("/api/topic/evaluate", json={"topic": "降低车间设备故障率"}).json()
    assert result["total"] == 19 and result["references_used"] == 1
    assert result["measurable"] == 3 and result["suggestions"] == ["补充目标值"]
    assert captured["role"] == "topic" and "历史课题" in captured["prompt"]


def test_topic_evaluate_rejects_garbage_output(client, monkeypatch):
    from backend.app.api.endpoints import topic as topic_endpoint

    async def fake_chat(_messages, role=None):
        return "我觉得还行吧"

    monkeypatch.setattr(topic_endpoint, "chat", fake_chat)
    monkeypatch.setattr(topic_endpoint.rag_service, "search", _empty_rag)
    response = client.post("/api/topic/evaluate", json={"topic": "降低车间设备故障率"})
    assert response.status_code == 502 and response.json()["code"] == "TOPIC_EVAL_FAILED"


def test_data_advise_maps_actions_and_drops_bad_index(client, monkeypatch):
    from io import BytesIO

    from backend.app.api.endpoints import data as data_endpoint
    from backend.app.core import config as core_config

    core_config.get_settings().OPENAI_API_KEY = "sk-main"
    upload = client.post("/api/data/upload", files={"file": ("s.csv", BytesIO("类别,数量\n合计,30\nA,\n".encode()), "text/csv")}).json()

    async def fake_chat(_messages, role=None):
        return '{"overall":"先删合计行再补缺失","items":[{"index":0,"action":"drop_rows","reason":"合计行会重复统计"},{"index":1,"action":"forward_fill","reason":"补齐缺失"},{"index":99,"action":"keep","reason":"越界应被丢弃"}]}'

    monkeypatch.setattr(data_endpoint, "chat", fake_chat)
    result = client.post("/api/data/advise", json={"dataset_id": upload["dataset_id"]}).json()
    assert result["model"]
    assert result["overall"].startswith("先删")
    assert [item["index"] for item in result["items"]] == [0, 1]
    actions = {item["action"] for item in result["items"]}
    assert actions <= {"drop_rows", "forward_fill", "keep"}
    assert "median" not in actions  # 不在 suggested_actions 里的动作被强制降级


def test_chart_insight_validates_axes_and_falls_back(client, monkeypatch):
    from io import BytesIO

    from backend.app.api.endpoints import visualization as visualization_endpoint
    from backend.app.core import config as core_config

    core_config.get_settings().OPENAI_API_KEY = "sk-main"
    upload = client.post("/api/data/upload", files={"file": ("s.csv", BytesIO("月份,产量\n1月,10\n2月,20\n".encode()), "text/csv")}).json()
    client.post("/api/data/confirm", json={"dataset_id": upload["dataset_id"], "revision": 0})

    async def lying_chat(_messages, role=None):
        return '{"chart_type":"pie","x_axis":"不存在的列","y_axis":"产量","aggregation":"sum","reason":"r"}'

    monkeypatch.setattr(visualization_endpoint, "chat", lying_chat)
    bad = client.post("/api/visualization/insight", json={"dataset_id": upload["dataset_id"], "revision": 0}).json()
    assert bad["source"] == "rules" and bad["recommendation"]["x_axis"] == "月份"

    async def honest_chat(_messages, role=None):
        return '{"chart_type":"line","x_axis":"月份","y_axis":"产量","aggregation":"none","reason":"时间趋势","insight":"逐月上升","caveats":["样本仅两行"]}'

    monkeypatch.setattr(visualization_endpoint, "chat", honest_chat)
    good = client.post("/api/visualization/insight", json={"dataset_id": upload["dataset_id"], "revision": 0}).json()
    assert good["source"] == "ai" and good["insight"] == "逐月上升" and good["model"]


def test_chart_insight_requires_confirmation_first(client):
    from io import BytesIO

    upload = client.post("/api/data/upload", files={"file": ("s2.csv", BytesIO("月份,产量\n1月,10\n".encode()), "text/csv")}).json()
    response = client.post("/api/visualization/insight", json={"dataset_id": upload["dataset_id"], "revision": 0})
    assert response.status_code == 409 and response.json()["code"] == "DATA_REVISION_CONFLICT"
