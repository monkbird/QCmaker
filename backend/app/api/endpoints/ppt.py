from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from backend.app.services.ppt import ppt_service
import os
from fastapi.responses import FileResponse

router = APIRouter()

class PPTRequest(BaseModel):
    project_name: str
    topic: str
    data_summary: str
    discussion_summary: str
    chart_images: Optional[List[str]] = []

@router.post("/generate")
async def generate_ppt(request: PPTRequest):
    try:
        path = ppt_service.generate_ppt(
            request.project_name,
            request.topic,
            request.data_summary,
            request.discussion_summary,
            request.chart_images
        )
        return {"status": "success", "path": path, "filename": os.path.basename(path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/download/{filename}")
async def download_ppt(filename: str):
    file_path = os.path.join("backend/generated_ppts", filename)
    if os.path.exists(file_path):
        return FileResponse(file_path, filename=filename)
    raise HTTPException(status_code=404, detail="File not found")
