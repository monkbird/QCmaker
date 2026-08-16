from pathlib import Path

from backend.app.core.clients import get_embeddings_client
from backend.app.core.config import PROJECT_ROOT, get_settings
from backend.app.core.errors import AppException


class RAGService:
    def __init__(self):
        self.persist_directory = str(PROJECT_ROOT / "backend" / "data" / "chroma_db")
        self.vector_store = None
        self.config_revision = -1

    def _init_rag(self):
        from langchain_community.vectorstores import Chroma
        self.vector_store = Chroma(persist_directory=self.persist_directory, embedding_function=get_embeddings_client())
        self.config_revision = get_settings().CONFIG_REVISION

    def _check_init(self):
        if not self.vector_store or self.config_revision != get_settings().CONFIG_REVISION: self._init_rag()
        return True

    async def ingest_document(self, file_path: str, original_filename: str):
        self._check_init()
        if file_path.lower().endswith('.pdf'):
            from langchain_community.document_loaders import PyPDFLoader
            loader = PyPDFLoader(file_path)
        else:
            from langchain_core.documents import Document
            raw = Path(file_path).read_bytes(); text = None
            for encoding in ("utf-8", "gb18030"):
                try: text = raw.decode(encoding); break
                except UnicodeDecodeError: continue
            if text is None: raise AppException("DATA_FORMAT_UNSUPPORTED", "TXT 编码无法识别", 400)
            documents = [Document(page_content=text, metadata={})]
        if file_path.lower().endswith('.pdf'): documents = loader.load()
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(documents)
        for doc in splits: doc.metadata["source"] = original_filename
        self.vector_store.add_documents(splits)
        return len(splits)

    async def search(self, query: str, k: int = 4):
        self._check_init()
        return self.vector_store.similarity_search(query, k=k)

rag_service = RAGService()
