def test_provider_catalog_covers_domestic_and_global_services(client):
    response = client.get('/api/config/providers')
    assert response.status_code == 200
    providers = response.json()['providers']
    assert len(providers) >= 20
    assert {'cn', 'global', 'local', 'custom'} <= {item['region'] for item in providers}
    assert {'openai', 'anthropic', 'gemini', 'deepseek', 'qwen', 'ollama'} <= {item['id'] for item in providers}
    assert all('models' not in item for item in providers)
    assert all(item['docs_url'] for item in providers)
    assert all(item['verified_at'] == '2026-08-22' for item in providers)


def test_catalog_covers_coding_plan_gateways(client):
    response = client.get('/api/config/providers')
    providers = {item['id']: item for item in response.json()['providers']}
    assert {'opencode', 'opencode_go', 'glm_coding', 'zai_coding'} <= set(providers)
    assert providers['opencode']['base_url'].startswith('https://opencode.ai/zen/')
    assert providers['glm_coding']['kind'] == 'plan'
    assert all(providers[item]['docs_url'] for item in ('opencode', 'opencode_go', 'glm_coding', 'zai_coding'))


def test_model_list_requires_provider_key_instead_of_returning_stale_catalog(client):
    response = client.post('/api/config/models', json={'provider': 'deepseek'})
    assert response.status_code == 400
    assert response.json()['code'] == 'LLM_KEY_REQUIRED'


def test_model_list_returns_live_vendor_models(client, monkeypatch):
    from backend.app.api.endpoints import config

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {'data': [{'id': 'deepseek-v4-flash'}, {'id': 'deepseek-v4-pro'}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get(self, _url, **_kwargs):
            return FakeResponse()

    monkeypatch.setattr(config.httpx, 'AsyncClient', lambda **_kwargs: FakeClient())
    response = client.post('/api/config/models', json={'provider': 'deepseek', 'api_key': 'test-key'})
    assert response.status_code == 200
    assert response.json() == {'models': ['deepseek-v4-flash', 'deepseek-v4-pro'], 'source': 'remote'}
