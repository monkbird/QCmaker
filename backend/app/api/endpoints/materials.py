from __future__ import annotations
import asyncio
import os
from pathlib import Path
from fastapi import APIRouter,Depends,File,Query,UploadFile,Header
from fastapi.responses import FileResponse
from backend.app.core.security import verify_access_token
from backend.app.services.materials import material_service
router=APIRouter(dependencies=[Depends(verify_access_token)])
_parse_slots=asyncio.Semaphore(2)
async def _parse_later(project_id,material_id,version):
    async with _parse_slots:
        try: await asyncio.to_thread(material_service.parse_material,project_id,material_id,version)
        except Exception: pass
@router.get('/projects/{project_id}/materials')
async def list_materials(project_id:str): return {'items':material_service.repository.list_materials(project_id),'next_cursor':None}
@router.post('/projects/{project_id}/materials',status_code=202)
async def upload_material(project_id:str,file:UploadFile=File(...),material_id:str|None=Query(None),base_version:int|None=Query(None),idempotency_key:str|None=Header(None,alias='Idempotency-Key')):
    async def chunks():
        while True:
            c=await file.read(1024*1024)
            if not c: break
            yield c
    item=await material_service.stream_original(project_id,file.filename or 'material.txt',chunks(),material_id=material_id,base_version=base_version,idempotency_key=idempotency_key)
    asyncio.create_task(_parse_later(project_id,item.material_id,item.version))
    return item.model_dump(mode='json',exclude={'original_path'})
@router.get('/projects/{project_id}/materials/{material_id}/parse')
async def parse_manifest(project_id:str,material_id:str,version:int=Query(...,ge=1),cursor:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=500)):
    m=await asyncio.to_thread(material_service.get_parse_manifest,project_id,material_id,version); total=len(m.units); m.units=m.units[cursor:cursor+limit]; m.next_cursor=str(cursor+limit) if cursor+limit<total else None; return m.model_dump(mode='json')
@router.post('/projects/{project_id}/materials/{material_id}/parse')
async def parse_material(project_id:str,material_id:str,version:int=Query(...,ge=1)):
    result=await asyncio.to_thread(material_service.parse_material,project_id,material_id,version,failed_unit_ids=[])
    return result.model_dump(mode='json')
@router.post('/projects/{project_id}/materials/{material_id}/parse/retry',status_code=202)
async def retry_parse(project_id:str,material_id:str,version:int=Query(...,ge=1),payload:dict|None=None):
    failed_unit_ids=(payload or {}).get('failed_unit_ids') or []
    async def retry_later():
        async with _parse_slots:
            try: await asyncio.to_thread(material_service.parse_material,project_id,material_id,version,failed_unit_ids=failed_unit_ids)
            except Exception: pass
    asyncio.create_task(retry_later()); return {'status':'queued','material_id':material_id,'version':version}
@router.get('/projects/{project_id}/materials/{material_id}/original')
async def original(project_id:str,material_id:str,version:int=Query(...,ge=1)):
    item=material_service.repository.get_version(project_id,material_id,version)
    path=material_service.read_original(project_id,material_id,version)
    return FileResponse(path,filename=Path(item.filename).name)
@router.post('/projects/{project_id}/materials/{material_id}/cleaning-preview')
async def cleaning_preview(project_id:str,material_id:str,payload:dict):
    return material_service.preview_cleaning(project_id,material_id,int(payload['base_version']),payload.get('operations',[])).model_dump(mode='json')
@router.post('/projects/{project_id}/materials/{material_id}/cleaning-apply')
async def cleaning_apply(project_id:str,material_id:str,payload:dict):
    return material_service.apply_cleaning(project_id,material_id,payload['preview_id'],payload['diff_digest'],payload.get('confirmed_operation_ids',[])).model_dump(mode='json')
@router.post('/projects/{project_id}/materials/{material_id}/cleaning-undo')
async def cleaning_undo(project_id:str,material_id:str,payload:dict):
    return material_service.undo_cleaning(project_id,material_id,int(payload['base_version']),int(payload['restore_version'])).model_dump(mode='json')
