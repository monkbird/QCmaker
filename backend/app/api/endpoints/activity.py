from fastapi import APIRouter, Depends
from backend.app.core.security import verify_access_token
from backend.app.core.errors import AppException
from backend.app.models.activity import ActivityEntry, ActivityInput
from backend.app.repositories.database import connect, transaction
from backend.app.services.timeline_checks import check_timeline
import json, uuid
from datetime import UTC,datetime
router=APIRouter(dependencies=[Depends(verify_access_token)])
def _rows(project_id):
 db=connect()
 try: rows=db.execute("SELECT payload_json FROM project_activity WHERE project_id=? AND event_type='activity_version' ORDER BY created_at",(project_id,)).fetchall()
 finally: db.close()
 latest = {}
 for row in rows:
  item = ActivityEntry.model_validate(json.loads(row['payload_json']))
  if item.event_id not in latest or item.revision > latest[item.event_id].revision:
   latest[item.event_id] = item
 return list(latest.values())
@router.get('/projects/{project_id}/activities')
async def list_activities(project_id:str): return {'activities':_rows(project_id)}
@router.post('/projects/{project_id}/activities')
async def add_activity(project_id:str, request:ActivityInput):
 event_id=request.event_id or 'activity_'+uuid.uuid4().hex
 with transaction(immediate=True) as db:
  latest=db.execute("SELECT COALESCE(MAX(json_extract(payload_json,'$.revision')),0) FROM project_activity WHERE project_id=? AND event_type='activity_version' AND json_extract(payload_json,'$.event_id')=?",(project_id,event_id)).fetchone()[0]
  if request.expected_revision != latest: raise AppException('REVISION_CONFLICT','活动记录已更新，请刷新后重试',409)
  item=ActivityEntry(project_id=project_id,event_id=event_id,revision=latest+1,**request.model_dump(exclude={'expected_revision','event_id'}))
  db.execute('INSERT INTO project_activity(project_id,event_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)',(project_id,str(uuid.uuid4()),'activity_version',item.model_dump_json(),datetime.now(UTC).isoformat()))
 return item
@router.post('/projects/{project_id}/timeline/check')
async def timeline_check(project_id:str, records:list[dict]|None=None): return check_timeline(records if records is not None else [x.model_dump(mode='json') for x in _rows(project_id)])
@router.get('/projects/{project_id}/timeline/check')
async def timeline_check_saved(project_id:str): return check_timeline([x.model_dump(mode='json') for x in _rows(project_id)])
