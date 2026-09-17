from fastapi import APIRouter, Body, Depends, Query
from backend.app.core.security import verify_access_token
from backend.app.models.authoring import *
from backend.app.services.authoring import authoring_service
from backend.app.services.qc_paths import chapter_path
from backend.app.models.authoring import ChangeRequest, ChangeApplyRequest, GenerateChapterRequest, SourceRecord
from backend.app.services.authoring_changes import preview_change, apply_change
from backend.app.repositories.authoring_repository import authoring_repository
from backend.app.repositories.database import connect, transaction
from backend.app.core.errors import AppException
from datetime import UTC, datetime
from uuid import uuid4
import json

router=APIRouter(dependencies=[Depends(verify_access_token)])

@router.get('/projects/{project_id}/context')
async def get_context(project_id: str):
    return authoring_service.get_context(project_id) or ScenarioCard(project_id=project_id)

@router.put('/projects/{project_id}/context')
async def put_context(project_id: str, request: ScenarioCard, expected_revision: int = Query(..., ge=0)):
    if request.project_id != project_id: raise AppException('PROJECT_CONFLICT','场景不属于当前项目',422)
    return authoring_service.save_context(request, expected_revision)

@router.get('/projects/{project_id}/chapters')
async def list_chapters(project_id: str): return {'chapters': authoring_service.list_chapters(project_id), 'path': authoring_service.path(project_id), 'standard_status': 'reference_unconfirmed'}

@router.get('/projects/{project_id}/chapters/{chapter_id}/snapshot')
async def get_snapshot(project_id: str, chapter_id: str, revision: int | None = Query(None, ge=1)):
    return authoring_service.get_snapshot(project_id,chapter_id,revision)

@router.post('/projects/{project_id}/chapters/{chapter_id}/generate')
async def generate(project_id: str, chapter_id: str, request: GenerateChapterRequest | None = Body(None), expected_revision: int | None = Query(None, ge=0), operation_id: str | None = Query(None, min_length=1)):
    if request is None:
        if expected_revision is None or operation_id is None: raise AppException('REQUEST_INVALID', '需要预期版本与操作编号', 422)
        request = GenerateChapterRequest(expected_revision=expected_revision, operation_id=operation_id)
    return await authoring_service.generate_chapter(project_id,chapter_id,request.expected_revision,request.operation_id,request.evidence_refs)

@router.get('/projects/{project_id}/operations/{operation_id}')
def operation_status(project_id: str, operation_id: str):
    value = authoring_repository.operation(project_id, operation_id)
    if value is None: raise AppException('OPERATION_NOT_FOUND', '操作不存在', 404)
    return value

@router.get('/projects/{project_id}/chapters/{chapter_id}/history')
def chapter_history(project_id: str, chapter_id: str):
    db = connect()
    try:
        rows = list(db.execute('SELECT revision,updated_at,snapshot_json FROM chapters WHERE project_id=? AND chapter_id=? ORDER BY revision DESC', (project_id,chapter_id)))
        return {'revisions': [{'revision':r['revision'],'updated_at':r['updated_at']} for r in rows],
                'snapshots': [json.loads(r['snapshot_json']) for r in rows]}
    finally: db.close()

@router.post('/projects/{project_id}/changes/preview')
def changes_preview(project_id: str, request: ChangeRequest): return preview_change(project_id, request)

@router.post('/projects/{project_id}/changes/apply')
def changes_apply(project_id: str, request: ChangeApplyRequest): return apply_change(project_id, request)

@router.post('/projects/{project_id}/sources')
def register_source(project_id: str, request: SourceRecord):
    if request.source_kind == 'simulation' and request.origin_kind != 'simulation': raise AppException('SOURCE_NATURE_INVALID', '模拟来源必须保留模拟标识', 422)
    with transaction(immediate=True) as db:
        current = db.execute("SELECT COALESCE(MAX(json_extract(payload_json,'$.revision')),0) FROM project_activity WHERE project_id=? AND event_type='source_version' AND json_extract(payload_json,'$.source_id')=?",(project_id,request.source_id)).fetchone()[0]
        if current != request.expected_revision: raise AppException('REVISION_CONFLICT', '来源版本已更新',409)
        value = request.model_dump(); value.pop('expected_revision'); value['revision'] = current + 1
        db.execute('INSERT INTO project_activity VALUES(?,?,?,?,?)',(project_id,str(uuid4()),'source_version',json.dumps(value,ensure_ascii=False),datetime.now(UTC).isoformat()))
    return value

@router.get('/projects/{project_id}/evidence')
def available_evidence(project_id: str):
    from backend.app.services.materials import material_service
    materials = material_service.repository.list_materials(project_id)
    refs = material_service.list_evidence(project_id, [m.material_id if hasattr(m,'material_id') else m['material_id'] for m in materials])
    db = connect()
    try:
        rows = db.execute("SELECT payload_json FROM project_activity WHERE project_id=? AND event_type='source_version' ORDER BY created_at", (project_id,)).fetchall()
    finally: db.close()
    latest = {}
    for row in rows:
        source = json.loads(row[0]); latest[source['source_id']] = source
    for source in latest.values():
        refs.append({'source_kind':source['source_kind'],'source_id':source['source_id'],'source_version':source['revision'],
                     'locator':source['locator'],'origin_kind':source['origin_kind'],'excerpt':source['text'][:300]})
    return {'refs': refs}

@router.get('/projects/{project_id}/chapters/{chapter_id}/recommendations')
def recommend_evidence(project_id: str, chapter_id: str):
    path = {item.chapter_id:item for item in authoring_service.path(project_id)}
    if chapter_id not in path: raise AppException('CHAPTER_NOT_FOUND','章节不属于当前路径',404)
    chapter = path[chapter_id]
    keywords = {
        'overview':['小组','成员','职责','培训'], 'select_topic':['问题','课题','现状','需求'],
        'current_situation':['调查','统计','样本','现状'], 'set_goal':['目标','指标','基线'],
        'feasibility':['试验','对照','资源','可行'], 'cause_analysis':['原因','影响','条件'],
        'cause_confirmation':['确认','验证','试验','判据'], 'countermeasure':['措施','方案','责任','计划'],
        'implementation':['实施','记录','时间','现场'], 'effect_check':['效果','对比','数据','测量'],
        'standardize':['制度','标准','巩固','持续'], 'summary':['总结','不足','改进','下一步'],
    }.get(chapter.slug, [])
    from backend.app.services.authoring import resolve_sources
    refs = available_evidence(project_id)['refs']
    from backend.app.models.evidence import EvidenceRef
    refs = [ref if isinstance(ref,EvidenceRef) else EvidenceRef.model_validate(ref) for ref in refs]
    suggestions = []
    for block in resolve_sources(project_id,refs):
        hits = [word for word in keywords if word in block.text]
        if hits:
            suggestions.append({'ref':block.ref,'score':len(hits),'reason':'完整解析内容中出现：'+'、'.join(hits),
                'supports':'可用于定位'+chapter.title+'的候选依据，需作者核对适用对象和时间',
                'cannot_support':'关键词相关不代表事实真实、因果成立或目标已经达到'})
    return {'chapter_id':chapter_id,'method':'keyword_locator','suggestions':sorted(suggestions,key=lambda x:-x['score'])}

@router.put('/projects/{project_id}/chapters/{chapter_id}')
async def update(project_id: str, chapter_id: str, request: ChapterUpdate):
    return authoring_service.update_chapter(project_id,chapter_id,request)

@router.post('/projects/{project_id}/chapters/{chapter_id}/review')
async def review(project_id: str, chapter_id: str, request: ReviewRequest): return authoring_service.review(project_id,chapter_id,request)

@router.post('/projects/{project_id}/chapters/{chapter_id}/evidence-verification')
async def verify(project_id: str, chapter_id: str, request: EvidenceVerificationRequest): return authoring_service.verify_evidence(project_id,chapter_id,request)
