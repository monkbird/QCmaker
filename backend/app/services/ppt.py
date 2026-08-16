from __future__ import annotations

import base64
import binascii
import io
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from pptx import Presentation
from pptx.util import Inches

from backend.app.core.config import PROJECT_ROOT, get_settings
from backend.app.core.errors import AppException
from backend.app.models.contracts import PPTRequest, PPTResult
from backend.app.repositories.database import connect, transaction

OUTPUT_DIR = PROJECT_ROOT / "backend" / "generated_ppts"
TEMPLATE_DIR = PROJECT_ROOT / "backend" / "templates"


def _add_bullets(prs: Presentation, title: str, items: list[str]) -> None:
    slide = prs.slides.add_slide(prs.slide_layouts[1]); slide.shapes.title.text = title; frame = slide.placeholders[1].text_frame; frame.clear()
    for index, item in enumerate(items):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph(); paragraph.text = item


def _decode_image(encoded: str) -> io.BytesIO:
    if encoded.startswith("data:"): encoded = encoded.split(",", 1)[-1]
    try: content = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc: raise AppException("PPT_IMAGE_INVALID", "图表图片不是合法 base64", 400) from exc
    if len(content) > 5 * 1024 * 1024 or not (content.startswith(b"\x89PNG\r\n\x1a\n") or content.startswith(b"\xff\xd8\xff")): raise AppException("PPT_IMAGE_INVALID", "仅支持不超过 5MB 的 PNG/JPEG", 400)
    return io.BytesIO(content)


def generate(request: PPTRequest) -> PPTResult:
    template = next(TEMPLATE_DIR.glob("*.pptx"), None) if TEMPLATE_DIR.exists() else None; prs = Presentation(template) if template else Presentation()
    title = prs.slides.add_slide(prs.slide_layouts[0]); title.shapes.title.text = request.project_name; title.placeholders[1].text = request.topic
    _add_bullets(prs, "现状与数据", [request.data_summary])
    _add_bullets(prs, "原因分析", request.discussion_summary.root_causes or [request.discussion_summary.problem])
    _add_bullets(prs, "对策与建议", request.discussion_summary.countermeasures)
    slide = prs.slides.add_slide(prs.slide_layouts[5]); slide.shapes.title.text = "数据图表"
    if request.chart_images:
        for index, encoded in enumerate(request.chart_images): slide.shapes.add_picture(_decode_image(encoded), Inches(0.8 + (index % 2) * 6.1), Inches(1.4 + (index // 2) * 1.9), width=Inches(5.5), height=Inches(1.7))
    else:
        textbox = slide.shapes.add_textbox(Inches(1), Inches(2.5), Inches(11), Inches(1)); textbox.text_frame.text = "暂未提供图表图片"
    _add_bullets(prs, "总结", [request.discussion_summary.summary])
    file_id = uuid4(); safe_name = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", request.project_name).strip("_")[:50] or "QC成果"; display_name = f"{safe_name}_QC成果.pptx"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True); final_path = (OUTPUT_DIR / f"{file_id}.pptx").resolve(); temp_path = OUTPUT_DIR / f".{file_id}.tmp.pptx"
    if os.path.commonpath([str(final_path), str(OUTPUT_DIR.resolve())]) != str(OUTPUT_DIR.resolve()): raise AppException("FILE_NOT_FOUND", "文件路径不合法", 400)
    prs.save(temp_path); os.replace(temp_path, final_path); now = datetime.now(UTC); expires = now + timedelta(days=get_settings().PPT_TTL_DAYS)
    with transaction(immediate=True) as db: db.execute("INSERT INTO files VALUES(?,?,?,?,?)", (str(file_id), display_name, str(final_path), now.isoformat(), expires.isoformat()))
    return PPTResult(file_id=file_id, display_name=display_name, expires_at=expires)


def resolve_download(file_id: str) -> tuple[Path, str]:
    db = connect()
    try: row = db.execute("SELECT * FROM files WHERE file_id=?", (file_id,)).fetchone()
    finally: db.close()
    if not row or datetime.fromisoformat(row["expires_at"]) <= datetime.now(UTC): raise AppException("FILE_NOT_FOUND", "文件不存在或已过期", 404)
    path = Path(row["disk_path"]).resolve()
    if os.path.commonpath([str(path), str(OUTPUT_DIR.resolve())]) != str(OUTPUT_DIR.resolve()) or not path.is_file(): raise AppException("FILE_NOT_FOUND", "文件不存在", 404)
    return path, row["display_name"]


def cleanup_expired() -> None:
    now = datetime.now(UTC).isoformat()
    with transaction(immediate=True) as db:
        rows = db.execute("SELECT file_id,disk_path FROM files WHERE expires_at<=?", (now,)).fetchall()
        for row in rows:
            try: Path(row["disk_path"]).unlink(missing_ok=True)
            except OSError: continue
            db.execute("DELETE FROM files WHERE file_id=?", (row["file_id"],))
