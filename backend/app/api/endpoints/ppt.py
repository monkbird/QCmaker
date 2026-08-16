from fastapi import APIRouter
from fastapi.responses import FileResponse

from backend.app.models.contracts import PPTRequest, PPTResult
from backend.app.services.ppt import generate, resolve_download

router = APIRouter()

@router.post("/generate", response_model=PPTResult)
def generate_ppt(request: PPTRequest): return generate(request)

@router.get("/download/{file_id}")
def download_ppt(file_id: str):
    path, display_name = resolve_download(file_id); return FileResponse(path, filename=display_name, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")
