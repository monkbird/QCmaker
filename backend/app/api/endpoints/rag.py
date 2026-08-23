import os
import tempfile
from uuid import uuid4

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field

from backend.app.core.errors import AppException
from backend.app.core.security import verify_access_token
from backend.app.services.document_parser import SUPPORTED_SUFFIXES
from backend.app.services.rag import rag_service

router = APIRouter(dependencies=[Depends(verify_access_token)])


@router.post("/ingest")
async def ingest_document(file: UploadFile = File(...)):
    filename = file.filename or "document.txt"; suffix = os.path.splitext(filename)[1].lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise AppException("DATA_FORMAT_UNSUPPORTED", "仅支持 TXT / Markdown / PDF / Word(.docx) / Excel(.xlsx/.xls) / CSV / PPT(.pptx)", 400)
    content = await file.read(10 * 1024 * 1024 + 1)
    if len(content) > 10 * 1024 * 1024: raise AppException("DATA_FILE_TOO_LARGE", "文件不能超过 10MB", 400)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp: tmp.write(content); tmp_path = tmp.name
        num_chunks = await rag_service.ingest_document(tmp_path, filename)
        return {"document_id": f"doc_{uuid4().hex}", "filename": filename, "chunks": num_chunks}
    finally:
        if tmp_path:
            try: os.unlink(tmp_path)
            except FileNotFoundError: pass

class RAGSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=4, ge=1, le=20)

@router.post("/search")
async def search_documents(request: RAGSearchRequest):
    results = await rag_service.search(request.query, request.k)
    return {"results": [{"content": doc.page_content, "metadata": doc.metadata, "score": None} for doc in results]}
