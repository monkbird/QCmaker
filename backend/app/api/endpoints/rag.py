import os
import asyncio
import tempfile

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field

from backend.app.core.errors import AppException
from backend.app.core.security import verify_access_token
from backend.app.services.document_parser import SUPPORTED_SUFFIXES
from backend.app.services.rag import rag_service
from backend.app.services.materials import material_service

router = APIRouter(dependencies=[Depends(verify_access_token)])


@router.post("/ingest")
async def ingest_document(file: UploadFile = File(...), project_id: str = Form(..., min_length=1, max_length=100)):
    filename = file.filename or "document.txt"; suffix = os.path.splitext(filename)[1].lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise AppException("DATA_FORMAT_UNSUPPORTED", "仅支持 TXT / Markdown / PDF / Word(.docx) / Excel(.xlsx/.xls) / CSV / PPT(.pptx)", 400)
    tmp_path = None
    try:
        item = await material_service.stream_original(project_id, filename, file_chunks(file), idempotency_key=f'legacy-{project_id}-{filename}')
        try:
            manifest = await asyncio.to_thread(material_service.parse_material, project_id, item.material_id, item.version)
            if not manifest.coverage_complete and not any(r.text.strip() for u in manifest.units for r in u.regions):
                raise AppException('DOCUMENT_TEXT_EMPTY','未能从文档中提取到文本内容',400)
            result = await rag_service.ingest_document(item.original_path, filename, project_id)
        except AppException: raise
        except Exception: result = {'document_id': f'legacy_{item.material_id}', 'filename': filename, 'chunks': 0}
        return {**result, 'material_id': item.material_id, 'version': item.version, 'readiness': item.readiness}
    finally:
        if tmp_path:
            try: os.unlink(tmp_path)
            except FileNotFoundError: pass

async def file_chunks(file):
    while True:
        chunk=await file.read(1024*1024)
        if not chunk: return
        yield chunk

class RAGSearchRequest(BaseModel):
    project_id: str = Field(min_length=1, max_length=100)
    query: str = Field(min_length=1, max_length=2000)
    k: int = Field(default=4, ge=1, le=20)

@router.post("/search")
async def search_documents(request: RAGSearchRequest):
    results = await rag_service.search(request.query, request.k, request.project_id)
    return {"results": [{"content": doc.page_content, "metadata": doc.metadata, "score": None} for doc in results]}


@router.get("/documents")
async def list_documents(project_id: str = Query(..., min_length=1, max_length=100)):
    docs = await rag_service.list_documents(project_id)
    from backend.app.services.materials import material_service
    for doc in docs:
        for item in material_service.repository.list_materials(project_id):
            if item['filename'] == doc.get('filename'):
                doc.update(material_id=item['material_id'], version=item['version'], readiness='unread'); break
    return {"documents": docs}


@router.delete("/documents/{document_id}")
async def delete_document(document_id: str, project_id: str = Query(..., min_length=1, max_length=100)):
    return {"deleted_chunks": await rag_service.delete_document(document_id, project_id)}
