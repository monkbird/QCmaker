import pytest

from backend.app.services.rag import RAGService


class Collection:
    name = 'qc_test'

    def __init__(self, rows):
        self.rows = rows

    def count(self):
        return len(self.rows)

    def get(self, where=None, limit=500, offset=0, include=None):
        conditions = where.get('$and', [where]) if where else []
        rows = [(key, value) for key, value in self.rows.items()
                if all(all(value.get(k) == v for k, v in condition.items()) for condition in conditions)]
        rows = rows[offset:offset + limit]
        return {'ids': [key for key, _ in rows], 'metadatas': [value for _, value in rows]}

    def delete(self, ids):
        for key in ids:
            self.rows.pop(key)


@pytest.mark.asyncio
async def test_metadata_admin_spans_collections_without_embedding(monkeypatch):
    service = RAGService()
    first = Collection({'a': {'project_id': 'p', 'document_id': 'doc', 'source': 'one'},
                        'b': {'project_id': 'other', 'document_id': 'doc', 'source': 'two'}})
    second = Collection({'c': {'project_id': 'p', 'document_id': 'doc', 'source': 'one'}})
    monkeypatch.setattr(service, '_admin_collections', lambda: [first, second])
    monkeypatch.setattr(service, '_check_init', lambda: pytest.fail('embedding initialization forbidden'))
    assert (await service.admin_documents('p'))[0]['chunks'] == 2
    result = await service.admin_delete('p', 'doc')
    assert result == {'deleted_chunks': 2, 'failed_collections': [], 'status': 'succeeded'}
    assert list(first.rows) == ['b']
    assert await service.admin_documents('p') == []


@pytest.mark.asyncio
async def test_metadata_delete_reports_partial_failure(monkeypatch):
    service = RAGService()
    collection = Collection({'a': {'project_id': 'p', 'document_id': 'd'}})
    monkeypatch.setattr(service, '_admin_collections', lambda: [collection])
    def fail(ids):
        raise OSError('locked')
    monkeypatch.setattr(collection, 'delete', fail)
    result = await service.admin_delete('p')
    assert result['status'] == 'partial'
    assert result['deleted_chunks'] == 0
    assert 'a' in collection.rows
