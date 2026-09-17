import asyncio
from datetime import UTC,datetime,timedelta
from pathlib import Path
import pytest
from backend.app.core.errors import AppException
from backend.app.models.materials import *
from backend.app.models.materials import Region
from backend.app.services.materials import MaterialService

class Repo:
 def __init__(self): self.v={}; self.u={}; self.ops={}; self.events=[]
 def list_versions(self,p,m): return self.v.get((p,m),[])
 def get_version(self,p,m,n):
  for x in self.v.get((p,m),[]):
   if x.version==n:return x
  raise AppException('MATERIAL_NOT_FOUND','missing',404)
 def save_version(self,x): self.v.setdefault((x.project_id,x.material_id),[]).append(x); return x
 def save_units(self,p,m,n,u): self.u[(p,m,n)]=u
 def get_units(self,p,m,n): return self.u[(p,m,n)]
 def save_preview(self,x): self.ops[x.preview_id]=x
 def get_preview(self,p,k):
  x=self.ops[k]
  if x.expires_at<=datetime.now(UTC): raise AppException('CLEANING_PREVIEW_EXPIRED','expired',409)
  return x
 def add_event(self,e): self.events.append(e)
 def upload_replay(self,p,k,h):
  x=self.ops.get(k)
  if not x:return None
  if x[0]!=h: raise AppException('IDEMPOTENCY_CONFLICT','conflict',409)
  return x[1]
 def record_upload_operation(self,p,k,h,x): self.ops[k]=(h,x)
 def atomic_version_event(self,item,units,event): self.save_version(item); self.save_units(item.project_id,item.material_id,item.version,units); self.add_event(event)

def seed(tmp_path):
 r=Repo(); s=MaterialService(tmp_path,r); item=MaterialVersion(project_id='p1',material_id='mat_12345678',version=1,original_sha256='a',original_path=str(tmp_path/'a.txt'),filename='a.txt',size_bytes=3,created_at=datetime.now(UTC)); r.save_version(item); r.save_units('p1',item.material_id,1,[ParseUnit(unit_id='u',kind='block',ordinal=1,locator='block',regions=[Region(region_id='r',kind='text',text='before')])]); return s,r,item

@pytest.mark.asyncio
async def test_stream_replay_and_hash_conflict(tmp_path):
 import asyncio
 if hasattr(asyncio,'WindowsSelectorEventLoopPolicy'): asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
 s,r,_=seed(tmp_path)
 async def c(): yield b'abc'
 one=await s.stream_original('p1','b.txt',c(),idempotency_key='k')
 r.ops['k']=(one.original_sha256,one)
 async def d(): yield b'abc'
 assert (await s.stream_original('p1','b.txt',d(),idempotency_key='k')).version==one.version

def test_cross_material_preview_rejected(tmp_path):
 s,r,item=seed(tmp_path); p=s.preview_cleaning('p1',item.material_id,1,[CleaningOperation(operation_id='x',category='document',target_locator='r',before='before',after='after',reason='x')]); p.material_id='mat_other'; r.ops[p.preview_id]=p
 with pytest.raises(AppException): s.apply_cleaning('p1',item.material_id,p.preview_id,p.diff_digest,['x'])

def test_text_update_and_undo_restores_units(tmp_path):
 s,r,item=seed(tmp_path); p=s.preview_cleaning('p1',item.material_id,1,[CleaningOperation(operation_id='x',category='document',target_locator='r',before='before',after='after',reason='x')]); rec=s.apply_cleaning('p1',item.material_id,p.preview_id,p.diff_digest,['x']); assert r.u[('p1',item.material_id,rec.version)][0].regions[0].text=='after'; undo=s.undo_cleaning('p1',item.material_id,rec.version,1); assert r.u[('p1',item.material_id,undo.version)][0].regions[0].text=='before'

def test_expired_preview_and_bad_target_do_not_write(tmp_path):
 s,r,item=seed(tmp_path); p=s.preview_cleaning('p1',item.material_id,1,[CleaningOperation(operation_id='x',category='document',target_locator='missing',before='a',after='b',reason='x')]); p.expires_at=datetime.now(UTC)-timedelta(seconds=1); r.ops[p.preview_id]=p; before=len(r.list_versions('p1',item.material_id))
 with pytest.raises(AppException): s.apply_cleaning('p1',item.material_id,p.preview_id,p.diff_digest,['x'])
 assert len(r.list_versions('p1',item.material_id))==before
