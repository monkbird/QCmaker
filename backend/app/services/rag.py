from __future__ import annotations

import asyncio
import hashlib
import logging
import threading

from backend.app.core.clients import get_embeddings_client
from backend.app.core.config import PROJECT_ROOT, get_settings

logger = logging.getLogger(__name__)


def _embedding_fingerprint() -> str:
    settings = get_settings()
    base_url = settings.LOCAL_LLM_URL if settings.USE_LOCAL_LLM else settings.OPENAI_BASE_URL
    model = (settings.EMBEDDING_MODEL or settings.LOCAL_LLM_MODEL) if settings.USE_LOCAL_LLM else settings.EMBEDDING_MODEL
    return hashlib.sha256(f'{base_url.rstrip("/")}|{model}'.encode()).hexdigest()[:12]


class RAGService:
    def __init__(self):
        self.persist_directory = str(PROJECT_ROOT / 'backend' / 'data' / 'chroma_db')
        self.vector_store = None
        self.collection_key = ''
        self.config_revision = -1
        self._lock = threading.RLock()

    def _collection_name(self) -> str:
        return f'qc_{_embedding_fingerprint()}'

    def _init_rag(self):
        try:
            from langchain_chroma import Chroma
        except ImportError:
            from langchain_community.vectorstores import Chroma
        collection = self._collection_name()
        self.vector_store = Chroma(persist_directory=self.persist_directory, collection_name=collection, embedding_function=get_embeddings_client())
        self.collection_key = collection
        self.config_revision = get_settings().CONFIG_REVISION
        self._migrate_legacy()

    def _migrate_legacy(self):
        # Old collections did not record project ownership. Preserve their vectors
        # without paying to embed again, but quarantine them from project searches.
        settings = get_settings()
        base = settings.LOCAL_LLM_URL if settings.USE_LOCAL_LLM else settings.OPENAI_BASE_URL
        model = (settings.EMBEDDING_MODEL or settings.LOCAL_LLM_MODEL) if settings.USE_LOCAL_LLM else settings.EMBEDDING_MODEL
        secret = '' if settings.USE_LOCAL_LLM else (settings.OPENAI_API_KEY or '')
        old_name = 'qc_' + hashlib.sha256(f'{base}|{model}|{secret}'.encode()).hexdigest()[:12]
        client = self.vector_store._client
        names = {getattr(c, 'name', c) for c in client.list_collections()}
        if old_name == self.collection_key or old_name not in names:
            return
        old = client.get_collection(old_name)
        for offset in range(0, old.count(), 500):
            rows = old.get(limit=500, offset=offset, include=['documents', 'metadatas', 'embeddings'])
            if rows['ids']:
                metadata = [{**(m or {}), 'project_id': '__legacy_unassigned__', 'legacy_collection': old_name} for m in rows['metadatas']]
                self.vector_store._collection.upsert(ids=['legacy_' + i for i in rows['ids']], documents=rows['documents'], embeddings=rows['embeddings'], metadatas=metadata)

    def _check_init(self):
        if not self.vector_store or self.collection_key != self._collection_name() or self.config_revision != get_settings().CONFIG_REVISION:
            self._init_rag()

    def _load_documents(self, file_path: str, original_filename: str):
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        from backend.app.services.document_parser import extract_documents
        splits = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200).split_documents(extract_documents(file_path, original_filename))
        for doc in splits:
            doc.metadata['source'] = original_filename
        return splits

    def _add_accounted(self, splits) -> int:
        # The embedding client owns redaction and accounting for both write/read.
        self.vector_store.add_documents(splits, ids=[doc.metadata['chunk_id'] for doc in splits])
        return len(splits)

    async def ingest_document(self, file_path: str, original_filename: str, project_id: str | None = None):
        if not project_id:
            from backend.app.core.errors import AppException
            raise AppException('PROJECT_REQUIRED', '上传资料必须关联项目', 400)
        splits = await asyncio.to_thread(self._load_documents, file_path, original_filename)
        identity = project_id + '\0' + original_filename + '\0' + '\0'.join(d.page_content for d in splits)
        document_id = 'doc_' + hashlib.sha256(identity.encode()).hexdigest()[:32]
        for index, doc in enumerate(splits):
            doc.metadata.update(project_id=project_id, document_id=document_id, chunk_id=f'{document_id}_{index}')
        def store():
            with self._lock:
                self._check_init()
                existing = self.vector_store.get(where={'document_id': document_id})
                if not existing['ids']:
                    self._add_accounted(splits)
                return {'document_id': document_id, 'filename': original_filename, 'chunks': len(splits)}
        return await asyncio.to_thread(store)

    async def search(self, query: str, k: int = 4, project_id: str | None = None):
        if not project_id:
            return []
        def retrieve():
            with self._lock:
                self._check_init()
                # Empty projects do not incur a query embedding call.
                if not self.vector_store.get(where={'project_id': project_id}, limit=1)['ids']:
                    return []
                return self.vector_store.similarity_search(query, k, filter={'project_id': project_id})
        return await asyncio.to_thread(retrieve)

    async def list_documents(self, project_id: str):
        def collect():
            with self._lock:
                self._check_init()
                documents = {}
                seen = set()
                for collection in self._document_collections():
                    rows = collection.get(where={'project_id': project_id})
                    for chunk_id, metadata in zip(rows['ids'], rows['metadatas']):
                        if chunk_id in seen:
                            continue
                        seen.add(chunk_id)
                        doc_id = metadata['document_id']
                        item = documents.setdefault(doc_id, {'document_id': doc_id, 'filename': metadata['source'], 'chunks': 0})
                        item['chunks'] += 1
                return list(documents.values())
        return await asyncio.to_thread(collect)

    async def delete_document(self, document_id: str, project_id: str):
        def delete():
            with self._lock:
                self._check_init()
                deleted = 0
                for collection in self._document_collections():
                    rows = collection.get(where={'$and': [{'project_id': project_id}, {'document_id': document_id}]})
                    if rows['ids']:
                        collection.delete(ids=rows['ids'])
                        deleted += len(rows['ids'])
                return deleted
        return await asyncio.to_thread(delete)

    def _document_collections(self):
        client = getattr(self.vector_store, '_client', None)
        if client is None:
            return [self.vector_store]
        # A model change must not hide the registry or resurrect deleted vectors.
        return [client.get_collection(getattr(item, 'name', item)) for item in client.list_collections()
                if str(getattr(item, 'name', item)).startswith('qc_')]


rag_service = RAGService()
