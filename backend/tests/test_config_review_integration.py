import json


def test_switch_to_saved_provider_uses_bound_credentials(client, isolated_settings):
    isolated_settings.OPENAI_API_KEY = 'old-test-key'
    isolated_settings.PROVIDER_CREDENTIALS = json.dumps({'deepseek': {'api_key': 'new-test-key', 'base_url': 'https://api.deepseek.com'}})
    response = client.post('/api/config/update', json={'llm_provider': 'deepseek', 'openai_base_url': 'https://api.deepseek.com', 'openai_model': 'test'})
    assert response.status_code == 200


def test_incomplete_role_model_is_rejected_not_silently_dropped(client):
    response = client.post('/api/config/update', json={'role_models': {'analyst': 'openai'}})
    assert response.status_code == 400


def test_custom_provider_models_use_saved_base_url(client, isolated_settings, monkeypatch):
    from backend.app.api.endpoints import config
    isolated_settings.PROVIDER_CREDENTIALS = json.dumps({'custom': {'api_key': 'test-key', 'base_url': 'https://custom.example/v1'}})
    captured = []
    async def fake_get(self, url, **kwargs):
        captured.append(url)
        return config.httpx.Response(200, json={'data': [{'id': 'saved-model'}]}, request=config.httpx.Request('GET', url))
    monkeypatch.setattr(config.httpx.AsyncClient, 'get', fake_get)
    response = client.post('/api/config/models', json={'provider': 'custom'})
    assert response.status_code == 200
    assert captured == ['https://custom.example/v1/models']
