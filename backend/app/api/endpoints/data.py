import json
import logging

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel

from backend.app.core.errors import AppException
from backend.app.core.llm_gateway import chat
from backend.app.core.security import verify_access_token
from backend.app.models.contracts import (
    CleaningAdviceItem,
    CleaningAdviceResponse,
    CleaningApplyRequest,
    CleaningPreviewResponse,
    ConfirmRequest,
    DatasetResponse,
    RevisionRequest,
)
from backend.app.repositories import dataset_repository
from backend.app.services.data_cleaning import analyze, apply_rules, parse_file, rows_from_frame
from backend.app.services.model_roles import describe_target

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=[Depends(verify_access_token)])

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


ADVISOR_PROMPT = """你是QC数据清洗顾问。针对检测出的数据问题给出业务解释与处置建议，不改动原始数值。
只输出合法 JSON：{"overall":"总体判断一句话","items":[{"index":0,"action":"keep|drop_rows|median|forward_fill|convert_number|convert_percent","reason":"理由"}]}。index 必须与输入的问题编号一致；没有把握的用 keep。不要 Markdown。"""


class CleanAdviseRequest(BaseModel):
    dataset_id: str


@router.post("/advise", response_model=CleaningAdviceResponse)
async def advise_cleaning(request: CleanAdviseRequest):
    dataset = dataset_repository.get(request.dataset_id)
    issue_lines = []
    for index, issue in enumerate(dataset.report.issues):
        sample = ""
        if issue.column and issue.row_ids:
            first_row = next((row for row in dataset.rows if row.row_id == issue.row_ids[0]), None)
            if first_row is not None: sample = f"，示例值：{first_row.values.get(issue.column)!r}"
        scope = issue.column or "整行"
        issue_lines.append(f"{index}. [{issue.issue_type}] {scope}，涉及 {len(issue.row_ids)} 行{sample}，可选动作：{'/'.join(issue.suggested_actions)}")
    profile = {"行数": len(dataset.rows), "列": [{"列名": column.name, "推断类型": column.inferred_type, "缺失数": column.missing_count, "异常数": column.outlier_count} for column in dataset.columns]}
    prompt = "数据画像：" + json.dumps(profile, ensure_ascii=False) + "\n检出问题：\n" + ("\n".join(issue_lines) if issue_lines else "（未检出问题）")
    raw = await chat([{"role": "system", "content": ADVISOR_PROMPT}, {"role": "user", "content": prompt}], role="data")
    try:
        parsed = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
        allowed_actions = [set(issue.suggested_actions) | {"keep"} for issue in dataset.report.issues]
        items = []
        for entry in parsed.get("items", []):
            index = int(entry["index"])
            if not 0 <= index < len(dataset.report.issues): continue
            action = str(entry.get("action", "keep"))
            if action not in allowed_actions[index]: action = "keep"
            items.append(CleaningAdviceItem(index=index, action=action, reason=str(entry.get("reason", ""))[:300]))
        return CleaningAdviceResponse(overall=str(parsed.get("overall", ""))[:800], items=items[:50], model=describe_target("data"))
    except (ValueError, KeyError, TypeError) as exc:
        logger.warning("cleaning advice parse failed: %s", exc)
        raise AppException("CLEAN_ADVICE_FAILED", "清洗建议解析失败，请重试或换用其他模型", 502) from exc
