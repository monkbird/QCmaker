import asyncio
import socket
from datetime import UTC, datetime, timedelta

import pytest
from starlette.requests import Request


def test_forwarded_header_does_not_change_client(isolated_settings):
    from backend.app.core.security import _client_ip
    request = Request({'type': 'http', 'client': ('8.8.8.8', 123), 'headers': [(b'x-forwarded-for', b'fake-client')]})
    assert _client_ip(request) == '8.8.8.8'


def test_ssrf_dns_private_and_unusual_ip(monkeypatch):
    from backend.app.core.errors import AppException
    from backend.app.core.security import validate_outbound_base_url
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', 80))])
    for url in ('http://127.1/v1', 'https://attacker.example/v1'):
        with pytest.raises(AppException):
            validate_outbound_base_url(url)


def test_saved_credential_cannot_follow_changed_endpoint(client, isolated_settings, monkeypatch):
    from backend.app.api.endpoints import config
    isolated_settings.OPENAI_API_KEY = 'test-saved-secret'
    monkeypatch.setattr(config, 'validate_outbound_base_url', lambda value, **kw: value.rstrip('/'))
    async def blocked_send(*a, **kw):
        raise config.httpx.ConnectError('offline test')
    monkeypatch.setattr(config.httpx.AsyncClient, 'send', blocked_send)
    response = client.post('/api/config/models', json={'provider': 'openai', 'base_url': 'https://attacker.example/v1'})
    assert response.status_code == 400
    assert response.json()['code'] == 'LLM_KEY_REQUIRED'


def test_key_rotation_preserves_vector_space(isolated_settings):
    from backend.app.services.rag import _embedding_fingerprint
    before = _embedding_fingerprint()
    isolated_settings.OPENAI_API_KEY = 'rotated-test-key'
    assert _embedding_fingerprint() == before


def test_unknown_cost_survives_ttl(client):
    from backend.app.repositories.database import transaction
    from backend.app.services.usage import get_usage, sweep_stale_reservations
    with transaction(immediate=True) as db:
        db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?,?)', ('old', 'req', 'x', 'unknown', '0.25', 'usage_unknown', (datetime.now(UTC)-timedelta(days=90)).isoformat()))
    sweep_stale_reservations()
    assert get_usage().unknown_cost
    assert float(get_usage().reserved_usd) == .25


def test_embedding_gateway_redacts_and_accounts_query(client):
    from backend.app.core.clients import AccountedEmbeddings
    from backend.app.services.usage import get_usage
    sent = []
    class Embeddings:
        def embed_query(self, text):
            sent.append(text)
            return [1., 2.]
        def embed_documents(self, texts):
            sent.extend(texts)
            return [[1., 2.] for _ in texts]
    gateway = AccountedEmbeddings(Embeddings(), 'openai', 'text-embedding-3-small')
    assert gateway.embed_query('联系 13812345678 和 abc@example.com') == [1., 2.]
    gateway.embed_documents(['联系 13812345678'])
    assert all('13812345678' not in text and 'abc@example.com' not in text for text in sent)
    assert get_usage().known_cost_usd > 0


def test_ingestion_requires_project(client):
    response = client.post('/api/rag/ingest', files={'file': ('a.txt', b'data')})
    assert response.status_code == 422


def test_connection_resolves_again_and_pins_checked_address(monkeypatch):
    from httpcore._backends.sync import SyncBackend

    from backend.app.core.errors import AppException
    from backend.app.core.security import outbound_http_clients, validate_outbound_base_url
    calls = []
    monkeypatch.setattr(SyncBackend, 'connect_tcp', lambda self, host, port, **kw: calls.append(host) or 'stream')
    sync, async_client = outbound_http_clients()
    try:
        validate_outbound_base_url('https://public.example/v1')
        backend = sync._transport._pool._network_backend
        assert backend.connect_tcp('public.example', 443) == 'stream'
        assert calls == ['8.8.8.8']
        monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.1', 443))])
        with pytest.raises(AppException):
            backend.connect_tcp('public.example', 443)
        assert calls == ['8.8.8.8']
    finally:
        sync.close()
        asyncio.run(async_client.aclose())


def test_async_connection_pins_checked_address(monkeypatch):
    from httpcore._backends.auto import AutoBackend

    from backend.app.core.security import outbound_http_clients
    calls = []
    async def fake_connect(self, host, port, **kw):
        calls.append(host)
        return 'stream'
    monkeypatch.setattr(AutoBackend, 'connect_tcp', fake_connect)
    sync, async_client = outbound_http_clients()
    async def run():
        assert await async_client._transport._pool._network_backend.connect_tcp('public.example', 443) == 'stream'
        await async_client.aclose()
    asyncio.run(run())
    sync.close()
    assert calls == ['8.8.8.8']


def test_chat_client_enforces_output_cap(isolated_settings, monkeypatch):
    import sys
    from types import SimpleNamespace

    from backend.app.core import clients
    captured = {}
    def chat_client(**kwargs):
        captured.update(kwargs)
        return kwargs
    monkeypatch.setitem(sys.modules, 'langchain_openai', SimpleNamespace(ChatOpenAI=chat_client))
    clients.clear_client_cache()
    clients.get_chat_client_for('test-key', 'https://public.example/v1', 'test-model')
    assert captured['max_tokens'] == isolated_settings.LLM_MAX_OUTPUT_TOKENS
    assert captured['max_retries'] == 0
    captured['http_client'].close()
    asyncio.run(captured['http_async_client'].aclose())
    clients.clear_client_cache()


def test_embedding_budget_blocks_before_dispatch(client, isolated_settings):
    from backend.app.core.clients import AccountedEmbeddings
    from backend.app.core.errors import AppException
    isolated_settings.MAX_BUDGET_USD = 0
    class Forbidden:
        def embed_query(self, text):
            raise AssertionError('must never dispatch')
    with pytest.raises(AppException) as exc:
        AccountedEmbeddings(Forbidden(), 'openai', 'text-embedding-3-small').embed_query('query')
    assert exc.value.code == 'BUDGET_EXCEEDED'


def test_dispatched_calls_remain_held_after_crash(client):
    from backend.app.repositories.database import transaction
    from backend.app.services.usage import get_usage, mark_dispatched, reserve, sweep_stale_reservations
    reservation = reserve('crashed', 'openai', 'gpt-4o-mini', 'hello')
    mark_dispatched(reservation)
    with transaction(immediate=True) as db:
        db.execute('UPDATE reservations SET created_at=? WHERE id=?', ((datetime.now(UTC)-timedelta(days=90)).isoformat(), reservation))
    sweep_stale_reservations()
    assert get_usage().unknown_cost and get_usage().reserved_usd > 0


def test_saved_credentials_cannot_change_address_on_update(client, isolated_settings):
    import json
    isolated_settings.OPENAI_API_KEY = 'test-key'
    isolated_settings.PROVIDER_CREDENTIALS = json.dumps({'deepseek': {'api_key': 'other-test-key'}})
    for payload in ({'openai_base_url': 'https://other.example/v1'},
                    {'provider_credentials': {'deepseek': {'base_url': 'https://other.example/v1'}}},
                    {'llm_provider': 'deepseek', 'openai_base_url': 'https://other.example/v1'}):
        response = client.post('/api/config/update', json=payload)
        assert response.status_code == 400 and response.json()['code'] == 'LLM_KEY_REQUIRED'


def test_document_registry_and_delete_survive_model_switch(isolated_settings, monkeypatch):
    from types import SimpleNamespace

    from backend.app.services.rag import RAGService
    class Collection:
        def __init__(self, docs): self.docs = docs
        def get(self, where=None):
            conditions = (where or {}).get('$and', [where or {}])
            docs = [d for d in self.docs if all(all(d.get(k) == v for k, v in c.items()) for c in conditions)]
            return {'ids': [d['chunk_id'] for d in docs], 'metadatas': docs}
        def delete(self, ids): self.docs = [d for d in self.docs if d['chunk_id'] not in ids]
    old = Collection([{'project_id': 'p', 'document_id': 'd', 'chunk_id': 'd_0', 'source': 'old.txt'}])
    current = Collection([])
    vector_client = SimpleNamespace(list_collections=lambda: ['qc_old', 'qc_current'], get_collection=lambda name: {'qc_old': old, 'qc_current': current}[name])
    current._client = vector_client
    service = RAGService()
    service.vector_store = current
    monkeypatch.setattr(service, '_check_init', lambda: None)
    assert asyncio.run(service.list_documents('p')) == [{'document_id': 'd', 'filename': 'old.txt', 'chunks': 1}]
    assert asyncio.run(service.delete_document('d', 'p')) == 1
    assert not old.docs


@pytest.mark.parametrize('url', ['http://[', 'https://public.example:bad/v1', 'https://public.example:99999/v1'])
def test_malformed_base_url_is_business_error(client, url):
    response = client.post('/api/config/update', json={'openai_base_url': url})
    assert response.status_code == 400
    assert response.json()['code'] == 'MODEL_BASE_URL_INVALID'


def test_chroma_persistence_rotation_and_legacy_quarantine(isolated_settings, tmp_path, monkeypatch):
    import hashlib

    import chromadb
    from chromadb.config import Settings as ChromaSettings
    from langchain_core.embeddings import Embeddings

    from backend.app.services import rag
    class OfflineEmbeddings(Embeddings):
        def embed_documents(self, texts): return [[float(len(t)), 1., 0.] for t in texts]
        def embed_query(self, text): return [float(len(text)), 1., 0.]
    monkeypatch.setenv('ANONYMIZED_TELEMETRY', 'False')
    monkeypatch.setattr(rag, 'get_embeddings_client', lambda: OfflineEmbeddings())
    directory = str(tmp_path / 'persistent-vectors')
    store = chromadb.PersistentClient(path=directory, settings=ChromaSettings(anonymized_telemetry=False))
    old_name = 'qc_' + hashlib.sha256(f'{isolated_settings.OPENAI_BASE_URL}|{isolated_settings.EMBEDDING_MODEL}|'.encode()).hexdigest()[:12]
    old = store.get_or_create_collection(old_name)
    old.add(ids=['legacy-row'], embeddings=[[1., 1., 0.]], documents=['Unassigned original data'], metadatas=[{'source': 'old.txt'}])
    service = rag.RAGService()
    service.persist_directory = directory
    file = tmp_path / 'new.txt'
    file.write_text('Project specific knowledge', encoding='utf-8')
    added = asyncio.run(service.ingest_document(str(file), 'new.txt', 'project'))
    assert asyncio.run(service.list_documents('project')) == [added]
    isolated_settings.OPENAI_API_KEY = 'rotated-test-key'
    isolated_settings.CONFIG_REVISION += 1
    restarted = rag.RAGService()
    restarted.persist_directory = directory
    hits = asyncio.run(restarted.search('knowledge', project_id='project'))
    assert hits and all(d.metadata['project_id'] == 'project' for d in hits)
    assert old.count() == 1
    assert restarted.vector_store.get(where={'project_id': '__legacy_unassigned__'})['documents'] == ['Unassigned original data']
    assert asyncio.run(restarted.delete_document(added['document_id'], 'project')) == 1
    assert asyncio.run(restarted.search('knowledge', project_id='project')) == []
