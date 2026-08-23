from __future__ import annotations

import asyncio
import hashlib
import logging
from uuid import uuid4

from backend.app.core.clients import get_embeddings_client
from backend.app.core.config import PROJECT_ROOT, get_settings
from backend.app.services.usage import estimate_tokens, reserve_embedding, settle_embedding

logger = logging.getLogger(__name__)


def _embedding_fingerprint() -> str:
    settings = get_settings()
    if settings.USE_LOCAL_LLM: base_url, model, secret = settings.LOCAL_LLM_URL, (settings.EMBEDDING_MODEL or settings.LOCAL_LLM_MODEL), ""
    else: base_url, model, secret = settings.OPENAI_BASE_URL, settings.EMBEDDING_MODEL, (settings.OPENAI_API_KEY or "")
    return hashlib.sha256(f"{base_url}|{model}|{secret}".encode()).hexdigest()[:12]


class RAGService:
    def __init__(self):
        self.persist_directory = str(PROJECT_ROOT / "backend" / "data" / "chroma_db")
        self.vector_store = None
        self.collection_key = ""

    def _collection_name(self) -> str:
        # Vectors from different embedding models live in separate collections so a
        # config change never mixes incompatible embedding spaces.
        return f"qc_{_embedding_fingerprint()}"

    def _init_rag(self):
        try:
            from langchain_chroma import Chroma
        except ImportError:
            from langchain_community.vectorstores import Chroma
        collection = self._collection_name()
        self.vector_store = Chroma(persist_directory=self.persist_directory, collection_name=collection, embedding_function=get_embeddings_client())
        self.collection_key = collection

    def _check_init(self):
        if not self.vector_store or self.collection_key != self._collection_name(): self._init_rag()

    def _load_documents(self, file_path: str, original_filename: str):
        from backend.app.services.document_parser import extract_documents
        documents = extract_documents(file_path, original_filename)
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        splits = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200).split_documents(documents)
        for doc in splits: doc.metadata["source"] = original_filename
        return splits

    def _add_accounted(self, splits) -> int:
        """Embed + store chunks while routing the cost through the budget ledger."""
        settings = get_settings(); provider = "local" if settings.USE_LOCAL_LLM else settings.LLM_PROVIDER; model = (settings.EMBEDDING_MODEL or settings.LOCAL_LLM_MODEL) if settings.USE_LOCAL_LLM else settings.EMBEDDING_MODEL
        estimated = sum(estimate_tokens(doc.page_content, model) for doc in splits)
        reservation_id = reserve_embedding(f"rag_{uuid4().hex}", provider, model, [doc.page_content for doc in splits])
        try:
            self.vector_store.add_documents(splits)
        except Exception:
            from backend.app.services.usage import release
            release(reservation_id); raise
        settle_embedding(reservation_id, f"rag_{uuid4().hex}", provider, model, max(1, estimated))
        return len(splits)

    async def ingest_document(self, file_path: str, original_filename: str):
        self._check_init()
        splits = await asyncio.to_thread(self._load_documents, file_path, original_filename)
        return await asyncio.to_thread(self._add_accounted, splits)

    async def search(self, query: str, k: int = 4):
        self._check_init()
        return await asyncio.to_thread(self.vector_store.similarity_search, query, k)


rag_service = RAGService()
