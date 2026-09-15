import pytest
from fastapi.testclient import TestClient

from backend.app.core.admin_security import hash_password


@pytest.fixture
def admin_client(isolated_storage, isolated_settings, monkeypatch):
    monkeypatch.setenv('ADMIN_ENABLED', 'true')
    monkeypatch.setenv('ADMIN_BOOTSTRAP_USERNAME', 'admin')
    monkeypatch.setenv('ADMIN_BOOTSTRAP_PASSWORD_HASH', hash_password('integration-password-123'))
    monkeypatch.setenv('ENVIRONMENT', 'development')
    from backend.main import app
    with TestClient(app, base_url='http://localhost') as client:
        response = client.post('/api/admin/auth/login', json={'username': 'admin', 'password': 'integration-password-123'}, headers={'Origin': 'http://localhost'})
        assert response.status_code == 200, response.text
        client.headers.update({'Origin': 'http://localhost', 'X-CSRF-Token': response.json()['csrf_token']})
        yield client


def test_real_router_all_read_views_return_safe_empty_state(admin_client):
    paths = ['dashboard/overview', 'dashboard/trends', 'dashboard/activity', 'usage/summary', 'usage/by-model',
             'budget/reservations', 'datasets', 'discussions', 'files', 'rag/projects', 'rag/collections',
             'system/health', 'system/storage', 'system/logs', 'security/sessions', 'security/settings', 'config', 'audit', 'operations']
    for path in paths:
        response = admin_client.get('/api/admin/' + path)
        assert response.status_code == 200, (path, response.text)
        assert response.headers['Cache-Control'] == 'no-store'
        assert 'password_hash' not in response.text
        assert 'session_secret' not in response.text
        assert 'integration-password-123' not in response.text


def test_read_polling_does_not_destroy_csrf(admin_client):
    for _ in range(3):
        assert admin_client.get('/api/admin/auth/me').status_code == 200
    assert admin_client.post('/api/admin/auth/activity', json={}, headers={'X-Admin-User-Activity': '1'}).status_code == 200
    assert admin_client.post('/api/admin/auth/reauth', json={'current_password': 'integration-password-123'}).status_code == 200
    assert admin_client.post('/api/admin/auth/logout').status_code == 200
    assert admin_client.get('/api/admin/dashboard/overview').status_code == 401


def test_delete_requires_reauthentication_and_preserves_idempotency(admin_client):
    from backend.app.repositories.database import transaction
    with transaction(immediate=True) as db:
        for name in ['first', 'second']:
            db.execute('INSERT INTO datasets VALUES(?,?,?,?,?,?,?,?,?,?)',
                       (name, name + '.csv', 0, None, '[]', '[]', '[]', '{}', '2026-01-01T00:00:00Z', '2099-01-01T00:00:00Z'))
    body = {'reason': '验收删除与重试', 'confirm_text': 'first'}
    headers = {'Idempotency-Key': 'delete-acceptance-key'}
    denied = admin_client.request('DELETE', '/api/admin/datasets/first', json=body, headers=headers)
    assert denied.status_code == 403
    assert admin_client.post('/api/admin/auth/reauth', json={'current_password': 'integration-password-123'}).status_code == 200
    first = admin_client.request('DELETE', '/api/admin/datasets/first', json=body, headers=headers)
    assert first.status_code == 200, first.text
    repeated = admin_client.request('DELETE', '/api/admin/datasets/first', json=body, headers=headers)
    assert repeated.status_code == 200, repeated.text
    assert repeated.json()['operation_id'] == first.json()['operation_id']
    conflict = admin_client.request('DELETE', '/api/admin/datasets/second', json={**body, 'confirm_text': 'second'}, headers=headers)
    assert conflict.status_code == 409, conflict.text
    assert admin_client.get('/api/admin/datasets/second').status_code == 200


def test_budget_revision_supports_consecutive_edits_and_rejects_stale_write(admin_client):
    assert admin_client.post('/api/admin/auth/reauth', json={'current_password': 'integration-password-123'}).status_code == 200
    initial = admin_client.get('/api/admin/dashboard/overview').json()['budget']
    for index, amount in enumerate(['1234', '1500']):
        current = admin_client.get('/api/admin/dashboard/overview').json()['budget']
        response = admin_client.put('/api/admin/budget/limit', json={
            'reason': '验收连续预算调整', 'confirm_text': 'MAX_BUDGET_USD',
            'expected_revision': current['revision'], 'max_budget_usd': amount,
        }, headers={'Idempotency-Key': f'budget-edit-{index}'})
        assert response.status_code == 200, response.text
        refreshed = admin_client.get('/api/admin/dashboard/overview').json()['budget']
        assert float(refreshed['limit_usd']) == float(amount)
        assert refreshed['revision'] == current['revision'] + 1
    stale = admin_client.put('/api/admin/budget/limit', json={
        'reason': '验收旧版本冲突', 'confirm_text': 'MAX_BUDGET_USD',
        'expected_revision': initial['revision'], 'max_budget_usd': '10',
    }, headers={'Idempotency-Key': 'budget-stale'})
    assert stale.status_code == 409
    assert float(admin_client.get('/api/admin/dashboard/overview').json()['budget']['limit_usd']) == 1500


def test_dataset_delete_rolls_back_when_terminal_audit_fails(admin_client, monkeypatch):
    from backend.app.repositories.database import transaction
    from backend.app.services import admin_operations
    with transaction(immediate=True) as db:
        db.execute('INSERT INTO datasets VALUES(?,?,?,?,?,?,?,?,?,?)',
                   ('audit-protected', 'protected.csv', 0, None, '[]', '[]', '[]', '{}', '2026-01-01T00:00:00Z', '2099-01-01T00:00:00Z'))
    assert admin_client.post('/api/admin/auth/reauth', json={'current_password': 'integration-password-123'}).status_code == 200
    record = admin_operations.record_audit_tx
    def fail_terminal(db, **kwargs):
        if kwargs.get('result') == 'SUCCEEDED':
            raise RuntimeError('injected audit write failure')
        return record(db, **kwargs)
    monkeypatch.setattr(admin_operations, 'record_audit_tx', fail_terminal)
    with pytest.raises(RuntimeError, match='injected audit write failure'):
        admin_client.request('DELETE', '/api/admin/datasets/audit-protected',
                             json={'reason': '验收审计故障回滚', 'confirm_text': 'audit-protected'},
                             headers={'Idempotency-Key': 'audit-rollback'})
    assert admin_client.get('/api/admin/datasets/audit-protected').status_code == 200


def test_rag_retry_completes_after_http_timeout_without_duplicate_side_effect(admin_client, monkeypatch):
    import asyncio
    import time

    from backend.app.services.rag import rag_service
    calls = []
    async def deletion(project_id, document_id=None):
        calls.append((project_id, document_id))
        if len(calls) == 1:
            return {'deleted_chunks': 2, 'failed_collections': ['retry-test'], 'status': 'partial'}
        await asyncio.sleep(3.2)
        return {'deleted_chunks': 3, 'failed_collections': [], 'status': 'succeeded'}
    monkeypatch.setattr(rag_service, 'admin_delete', deletion)
    assert admin_client.post('/api/admin/auth/reauth', json={'current_password': 'integration-password-123'}).status_code == 200
    body = {'reason': 'isolated partial retry acceptance', 'confirm_text': 'project-test'}
    first = admin_client.post('/api/admin/rag/projects/project-test/purge', json=body, headers={'Idempotency-Key': 'rag-first'})
    assert first.status_code == 200, first.text
    operation_id = first.json()['operation_id']
    assert first.json()['state'] == 'partial'
    retry = admin_client.post(f'/api/admin/operations/{operation_id}/retry', json=body, headers={'Idempotency-Key': 'rag-retry'})
    assert retry.status_code == 202, retry.text
    assert retry.json()['operation_id'] == operation_id
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = admin_client.get(f'/api/admin/operations/{operation_id}').json()
        if current['state'] != 'running':
            break
        time.sleep(0.1)
    assert current['state'] == 'succeeded', current
    assert current['result']['deleted_chunks'] == 5
    assert current['result']['failed_collections'] == []
    repeat = admin_client.post(f'/api/admin/operations/{operation_id}/retry', json=body, headers={'Idempotency-Key': 'rag-retry'})
    assert repeat.status_code == 200
    assert len(calls) == 2


def test_probe_uses_matching_provider_credential_and_reported_usage(admin_client, isolated_settings, monkeypatch):
    import json
    from types import SimpleNamespace

    from backend.app.core import security
    from backend.app.services import usage
    isolated_settings.OPENAI_API_KEY = 'active-provider-only'
    isolated_settings.PROVIDER_CREDENTIALS = json.dumps({'anthropic': {'api_key': 'anthropic-only', 'base_url': 'https://api.anthropic.com/v1'}})
    requests, settlements = [], []
    class Client:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None
        async def post(self, url, **kwargs):
            requests.append((url, kwargs))
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {'usage': {'input_tokens': 7, 'output_tokens': 1}})
    monkeypatch.setattr(security, 'outbound_http_clients', lambda local: (SimpleNamespace(close=lambda: None), Client()))
    monkeypatch.setattr(usage, 'settle', lambda *args, **kwargs: settlements.append((args, kwargs)))
    body = {'provider': 'anthropic', 'model': 'isolated-test', 'reason': 'offline provider isolation', 'confirm_text': 'anthropic/isolated-test'}
    denied = admin_client.post('/api/admin/system/probe/llm', json=body, headers={'Idempotency-Key': 'probe-test'})
    assert denied.status_code == 403
    assert not requests
    assert admin_client.post('/api/admin/auth/reauth', json={'current_password': 'integration-password-123'}).status_code == 200
    response = admin_client.post('/api/admin/system/probe/llm', json=body, headers={'Idempotency-Key': 'probe-test'})
    assert response.status_code == 200, response.text
    assert requests[0][0] == 'https://api.anthropic.com/v1/messages'
    assert requests[0][1]['headers']['x-api-key'] == 'anthropic-only'
    assert 'active-provider-only' not in str(requests)
    assert settlements[0][0][4:6] == (7, 1)
    assert settlements[0][1]['usage_known'] is True
    repeated = admin_client.post('/api/admin/system/probe/llm', json=body, headers={'Idempotency-Key': 'probe-test'})
    assert repeated.status_code == 200
    assert len(requests) == 1
