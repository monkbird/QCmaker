"""Append-only authoring storage with optimistic revisions and operation records."""
import hashlib
import json
from datetime import UTC, datetime
from uuid import uuid4

from backend.app.core.errors import AppException
from backend.app.models.authoring import ScenarioCard
from backend.app.models.evidence import ChapterSnapshot
from backend.app.repositories.database import connect, transaction


def _now(): return datetime.now(UTC).isoformat()
def _json(value): return json.dumps(value.model_dump(mode='json') if hasattr(value,'model_dump') else value, ensure_ascii=False)
def _event_id(project, operation): return 'authoring_' + hashlib.sha256(f'{project}:{operation}'.encode()).hexdigest()


class AuthoringRepository:
    def operation(self, project_id, operation_id):
        db=connect()
        try:
            row=db.execute('SELECT payload_json FROM project_activity WHERE project_id=? AND event_id=?',(project_id,_event_id(project_id,operation_id))).fetchone()
            return json.loads(row[0]) if row else None
        finally: db.close()

    def claim_operation(self, project_id, operation_id, digest):
        with transaction(immediate=True) as db:
            eid=_event_id(project_id,operation_id)
            row=db.execute('SELECT payload_json FROM project_activity WHERE event_id=?',(eid,)).fetchone()
            if row:
                value=json.loads(row[0])
                if value.get('digest') != digest: raise AppException('OPERATION_CONFLICT','操作编号已用于不同输入',409)
                if value['state']=='complete': return ChapterSnapshot.model_validate(value['snapshot'])
                raise AppException('OPERATION_PENDING','该生成操作已发起，请查询任务状态；失败后使用新的操作编号重试',409,{'state':value['state']})
            db.execute('INSERT INTO project_activity VALUES(?,?,?,?,?)',(project_id,eid,'authoring_operation',_json({'operation_id':operation_id,'digest':digest,'state':'running'}),_now()))
        return None

    def fail_operation(self,project_id,operation_id,code):
        with transaction(immediate=True) as db:
            row=db.execute('SELECT payload_json FROM project_activity WHERE event_id=?',(_event_id(project_id,operation_id),)).fetchone()
            if row:
                value=json.loads(row[0]);value.update(state='failed',error=code)
                db.execute('UPDATE project_activity SET payload_json=? WHERE event_id=?',(_json(value),_event_id(project_id,operation_id)))

    def get_operation_snapshot(self,project_id,operation_id):
        value=self.operation(project_id,operation_id)
        return ChapterSnapshot.model_validate(value['snapshot']) if value and value.get('state')=='complete' else None

    def get_context(self,project_id):
        db=connect()
        try: row=db.execute('SELECT context_json FROM project_contexts WHERE project_id=?',(project_id,)).fetchone()
        finally: db.close()
        return ScenarioCard.model_validate_json(row[0]) if row else None

    def save_context(self,context,expected_revision):
        with transaction(immediate=True) as db:
            row=db.execute('SELECT revision FROM project_contexts WHERE project_id=?',(context.project_id,)).fetchone()
            current=row[0] if row else 0
            if current != expected_revision: raise AppException('REVISION_CONFLICT','场景已更新，请刷新后重试',409,{'current_revision':current})
            saved=context.model_copy(update={'revision':current+1})
            db.execute('INSERT INTO project_contexts VALUES(?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET context_json=excluded.context_json,revision=excluded.revision,updated_at=excluded.updated_at',(context.project_id,_json(saved),saved.revision,_now()))
            db.execute('INSERT INTO project_activity VALUES(?,?,?,?,?)',(context.project_id,str(uuid4()),'context_version',_json(saved),_now()))
        return saved

    def get_snapshot(self,project_id,chapter_id,revision=None):
        db=connect()
        try:
            query='SELECT snapshot_json FROM chapters WHERE project_id=? AND chapter_id=?'
            args=[project_id,chapter_id]
            if revision is not None: query+=' AND revision=?';args.append(revision)
            row=db.execute(query+' ORDER BY revision DESC LIMIT 1',args).fetchone()
        finally: db.close()
        if not row: raise AppException('CHAPTER_NOT_FOUND','章节快照不存在',404)
        return ChapterSnapshot.model_validate_json(row[0])

    def list_chapters(self,project_id):
        db=connect()
        try: rows=db.execute('SELECT snapshot_json FROM chapters c WHERE project_id=? AND revision=(SELECT MAX(revision) FROM chapters WHERE project_id=c.project_id AND chapter_id=c.chapter_id) ORDER BY chapter_id',(project_id,)).fetchall()
        finally: db.close()
        return [ChapterSnapshot.model_validate_json(row[0]) for row in rows]

    def save_snapshot(self,snapshot,expected_revision,operation_id=None,audit=None):
        with transaction(immediate=True) as db:
            operation=None
            if operation_id:
                row=db.execute('SELECT payload_json FROM project_activity WHERE event_id=?',(_event_id(snapshot.project_id,operation_id),)).fetchone()
                operation=json.loads(row[0]) if row else None
                if operation and operation.get('state')=='complete':
                    previous=ChapterSnapshot.model_validate(operation['snapshot'])
                    if previous.chapter_id!=snapshot.chapter_id: raise AppException('OPERATION_CONFLICT','操作编号已被占用',409)
                    return previous
            current=db.execute('SELECT COALESCE(MAX(revision),0) FROM chapters WHERE project_id=? AND chapter_id=?',(snapshot.project_id,snapshot.chapter_id)).fetchone()[0]
            if current!=expected_revision: raise AppException('REVISION_CONFLICT','章节已更新，请刷新后重试',409,{'current_revision':current})
            saved=snapshot.model_copy(update={'revision':current+1})
            db.execute('INSERT INTO chapters VALUES(?,?,?,?,?)',(saved.project_id,saved.chapter_id,saved.revision,_json(saved),_now()))
            for ref in saved.evidence_refs:
                db.execute('INSERT OR IGNORE INTO source_dependencies VALUES(?,?,?,?,?)',(saved.project_id,'chapter',saved.chapter_id,ref.source_id,ref.source_version))
            if audit:
                db.execute('INSERT INTO chapter_reviews VALUES(?,?,?,?,?,?,?)',(saved.project_id,saved.chapter_id,saved.revision,saved.review_state,audit['reviewer_id'],_now(),_json(audit)))
            if operation_id:
                value={**(operation or {}),'operation_id':operation_id,'state':'complete','snapshot':saved.model_dump(mode='json')}
                db.execute('INSERT INTO project_activity VALUES(?,?,?,?,?) ON CONFLICT(event_id) DO UPDATE SET payload_json=excluded.payload_json',(saved.project_id,_event_id(saved.project_id,operation_id),'authoring_operation',_json(value),_now()))
        return saved

    def save_review(self,snapshot,reviewer_id,note):
        with transaction(immediate=True) as db:
            db.execute('INSERT OR IGNORE INTO chapter_reviews VALUES(?,?,?,?,?,?,?)',(snapshot.project_id,snapshot.chapter_id,snapshot.revision,snapshot.review_state,reviewer_id,_now(),note))


authoring_repository=AuthoringRepository()
