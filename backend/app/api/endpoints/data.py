from fastapi import APIRouter, File, UploadFile

from backend.app.core.errors import AppException
from backend.app.models.contracts import CleaningApplyRequest, CleaningPreviewResponse, ConfirmRequest, DatasetResponse, RevisionRequest
from backend.app.repositories import dataset_repository
from backend.app.services.data_cleaning import analyze, apply_rules, parse_file, rows_from_frame

router = APIRouter()

@router.post("/upload", response_model=DatasetResponse)
async def upload_data(file: UploadFile = File(...)):
    limit = 10 * 1024 * 1024; chunks: list[bytes] = []; size = 0
    while chunk := await file.read(1024 * 1024):
        size += len(chunk)
        if size > limit: raise AppException("DATA_FILE_TOO_LARGE", "文件不能超过 10MB", 400, {"limit_bytes": limit})
        chunks.append(chunk)
    filename = file.filename or "upload.csv"; rows = rows_from_frame(parse_file(b"".join(chunks), filename)); columns, report = analyze(rows)
    return dataset_repository.create(filename, rows, columns, report)


@router.get("/{dataset_id}", response_model=DatasetResponse)
def get_dataset(dataset_id: str): return dataset_repository.get(dataset_id)


@router.post("/preview", response_model=CleaningPreviewResponse)
def preview(request: CleaningApplyRequest):
    dataset = dataset_repository.get(request.dataset_id)
    if dataset.revision != request.base_revision: raise AppException("DATA_REVISION_CONFLICT", "数据版本已变化，请刷新后重试", 409, {"current_revision": dataset.revision})
    rows, _, report = apply_rules(dataset.rows, request.rules)
    return CleaningPreviewResponse(dataset_id=request.dataset_id, base_revision=request.base_revision, preview_rows=rows, report=report)


@router.post("/apply", response_model=DatasetResponse)
def apply(request: CleaningApplyRequest):
    dataset = dataset_repository.get(request.dataset_id); rows, columns, report = apply_rules(dataset.rows, request.rules)
    return dataset_repository.update(request.dataset_id, request.base_revision, rows, columns, report)


@router.post("/undo", response_model=DatasetResponse)
def undo(request: RevisionRequest):
    raw = dataset_repository.raw_rows(request.dataset_id); columns, report = analyze(raw, mode="undone")
    return dataset_repository.update(request.dataset_id, request.base_revision, raw, columns, report, restored=True)


@router.post("/confirm", response_model=DatasetResponse)
def confirm(request: ConfirmRequest): return dataset_repository.confirm(request.dataset_id, request.revision)
