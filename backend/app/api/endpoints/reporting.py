from fastapi import APIRouter, Depends

from backend.app.core.security import verify_access_token
from backend.app.models.reporting import ChapterChartRequest
from backend.app.repositories import artifact_repository
from backend.app.services import chapter_reporting

router = APIRouter(dependencies=[Depends(verify_access_token)])


@router.post('/chapter-charts')
def generate_chart(request: ChapterChartRequest):
    return chapter_reporting.generate_chart(request)


@router.get('/projects/{project_id}/artifacts')
def list_artifacts(project_id: str):
    return {'artifacts': artifact_repository.list_artifacts(project_id)}


@router.get('/projects/{project_id}/artifacts/{artifact_id}')
def get_artifact(project_id: str, artifact_id: str):
    return artifact_repository.get_artifact(project_id, artifact_id)
