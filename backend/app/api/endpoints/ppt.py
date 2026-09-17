from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse

from backend.app.core.security import verify_access_token
from backend.app.models.contracts import PPTRequest, PPTResult
from backend.app.services.ppt import generate, resolve_download
from backend.app.models.reporting import ChapterExportRequest, ExportPreviewRequest
from backend.app.services import chapter_reporting

router = APIRouter(dependencies=[Depends(verify_access_token)])

@router.post('/preflight')
def preflight_chapters(request: ExportPreviewRequest):
    return chapter_reporting.preview(request.project_id, request.chapter_revisions, request.chart_revisions)

@router.post('/generate-from-chapters')
def export_chapters(request: ChapterExportRequest):
    return chapter_reporting.export_chapters(request)

@router.post("/generate", response_model=PPTResult)
def generate_ppt(request: PPTRequest): return generate(request)

@router.get("/download/{file_id}")
def download_ppt(file_id: str):
    path, display_name = resolve_download(file_id); return FileResponse(path, filename=display_name, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation")
