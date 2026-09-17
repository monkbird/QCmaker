import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from backend.app.core.errors import AppException
from backend.app.models.authoring import ChangeApplyRequest, ChangeRequest
from backend.app.models.evidence import ChapterSnapshot
from backend.app.repositories.database import connect, transaction


def _dump(value): return json.dumps(value, ensure_ascii=False, sort_keys=True)


def preview_change(project_id: str, request: ChangeRequest):
    with transaction(immediate=True) as db:
        row = db.execute('SELECT * FROM project_contexts WHERE project_id=?', (project_id,)).fetchone()
        revision = row['revision'] if row else 0
        if revision != request.expected_revision:
            raise AppException('REVISION_CONFLICT', '场景已变化', 409, {'current_revision': revision})
        old = json.loads(row['context_json']) if row else {}
        new = request.context.model_dump(mode='json')
        new['project_id'] = project_id
        changed = [k for k in new if k not in {'revision', 'field_sources', 'project_id'} and new[k] != old.get(k)]
        substantive = bool(set(changed) - {'topic'})
        chapters = db.execute('SELECT chapter_id,MAX(revision) revision FROM chapters WHERE project_id=? GROUP BY chapter_id', (project_id,)).fetchall()
        affected = [{'chapter_id': r['chapter_id'], 'revision': r['revision']} for r in chapters] if substantive else []
        preview_id = str(uuid4())
        result = {'preview_id': preview_id, 'expected_revision': revision, 'changed_fields': changed,
                  'substantive': substantive, 'affected_chapters': affected, 'context': new,
                  'context_hash': hashlib.sha256(_dump(new).encode()).hexdigest()}
        db.execute('INSERT INTO project_activity VALUES(?,?,?,?,?)', (project_id, preview_id, 'change_preview', _dump(result), datetime.now(UTC).isoformat()))
        return result


def apply_change(project_id: str, request: ChangeApplyRequest):
    if request.context.topic_type != 'problem_solving' or request.context.standard_version != 'T/CAQ 10201-2020':
        raise AppException('PATH_UNSUPPORTED', '此类型或标准版本尚未核定', 422)
    with transaction(immediate=True) as db:
        row = db.execute("SELECT payload_json FROM project_activity WHERE project_id=? AND event_id=? AND event_type='change_preview'", (project_id, request.preview_id)).fetchone()
        if not row: raise AppException('PREVIEW_NOT_FOUND', '变更预览不存在', 404)
        preview = json.loads(row[0])
        current = db.execute('SELECT revision FROM project_contexts WHERE project_id=?', (project_id,)).fetchone()
        revision = current[0] if current else 0
        if revision != request.expected_revision or preview['expected_revision'] != revision:
            raise AppException('REVISION_CONFLICT', '场景已变化，请重新预览', 409)
        new = request.context.model_dump(mode='json'); new['project_id'] = project_id
        if hashlib.sha256(_dump(new).encode()).hexdigest() != preview['context_hash']:
            raise AppException('PREVIEW_CONFLICT', '输入与已预览内容不一致', 409)
        affected = {c['chapter_id']: c['revision'] for c in preview['affected_chapters']}
        if not set(request.chapter_ids).issubset(affected): raise AppException('CHAPTER_NOT_FOUND', '所选章节不在影响范围内', 404)
        now = datetime.now(UTC).isoformat()
        # All affected chapters are visibly stale; chosen ones additionally return to review.
        for chapter_id, version in affected.items():
            row = db.execute('SELECT revision,snapshot_json FROM chapters WHERE project_id=? AND chapter_id=? ORDER BY revision DESC LIMIT 1', (project_id, chapter_id)).fetchone()
            if not row or row['revision'] != version: raise AppException('REVISION_CONFLICT', '预览后章节已变化，请重新预览', 409)
            chapter = ChapterSnapshot.model_validate_json(row['snapshot_json'])
            update = {'revision': version + 1, 'stale': True, 'stale_reasons': sorted(set(chapter.stale_reasons + ['场景变化：' + '、'.join(preview['changed_fields'])]))}
            if chapter_id in request.chapter_ids: update['review_state'] = 'pending'
            chapter = chapter.model_copy(update=update)
            db.execute('INSERT INTO chapters VALUES(?,?,?,?,?)', (project_id, chapter_id, chapter.revision, chapter.model_dump_json(), now))
        new['revision'] = revision + 1
        db.execute('INSERT INTO project_contexts VALUES(?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET context_json=excluded.context_json,revision=excluded.revision,updated_at=excluded.updated_at', (project_id, _dump(new), revision + 1, now))
        db.execute('INSERT INTO project_activity VALUES(?,?,?,?,?)', (project_id, str(uuid4()), 'context_version', _dump(new), now))
        return {'context': new, 'affected_chapters': list(affected), 'review_chapters': request.chapter_ids}
