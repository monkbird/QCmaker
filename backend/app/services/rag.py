from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import TextLoader, PyPDFLoader
from backend.app.core.config import settings
import os
import shutil

class RAGService:
    def __init__(self):
        self.persist_directory = "./chroma_db"
        self.embeddings = None
        self.vector_store = None
        self._init_rag()

    def _init_rag(self):
        if settings.OPENAI_API_KEY:
            self.embeddings = OpenAIEmbeddings(
                openai_api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL
            )
            # Initialize Chroma
            self.vector_store = Chroma(
                persist_directory=self.persist_directory,
                embedding_function=self.embeddings
            )

    def _check_init(self):
        if not self.vector_store:
            self._init_rag()
        return self.vector_store is not None

    async def ingest_document(self, file_path: str, original_filename: str):
        if not self._check_init():
             return 0 # Or raise error

        # Determine loader based on extension
        if file_path.endswith('.pdf'):
            loader = PyPDFLoader(file_path)
        else:
            loader = TextLoader(file_path)
            
        documents = loader.load()
        
        # Split text
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(documents)
        
        # Add metadata
        for doc in splits:
            doc.metadata["source"] = original_filename
            
        # Add to vector store
        self.vector_store.add_documents(splits)
        self.vector_store.persist()
        
        return len(splits)

    async def search(self, query: str, k: int = 4):
        if not self._check_init():
            return []
        return self.vector_store.similarity_search(query, k=k)

rag_service = RAGService()
