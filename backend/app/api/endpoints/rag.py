from fastapi import APIRouter, UploadFile, File, HTTPException
from backend.app.services.rag import rag_service
import shutil
import os
import tempfile

router = APIRouter()

@router.post("/ingest")
async def ingest_document(file: UploadFile = File(...)):
    try:
        # Save to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as tmp:
            shutil.copyfileobj(file.file, tmp)
            tmp_path = tmp.name
            
        # Ingest
        num_chunks = await rag_service.ingest_document(tmp_path, file.filename)
        
        # Cleanup
        os.unlink(tmp_path)
        
        return {"status": "success", "chunks_ingested": num_chunks, "filename": file.filename}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/search")
async def search_documents(query: str):
    try:
        results = await rag_service.search(query)
        return {"results": [{"content": doc.page_content, "metadata": doc.metadata} for doc in results]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
