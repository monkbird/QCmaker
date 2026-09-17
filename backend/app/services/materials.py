from __future__ import annotations
import hashlib, json, os
import re
from threading import Lock
from collections import defaultdict
from datetime import UTC,datetime,timedelta
from pathlib import Path
from uuid import uuid4
from backend.app.core.errors import AppException
from backend.app.models.materials import *
from backend.app.repositories.material_repository import MaterialRepository,material_repository
from backend.app.services.document_parser import parse_source

class MaterialService:
    def __init__(self,storage_root=None,repository=None):
        self.storage_root=Path(storage_root or Path('backend/data/materials')); self.repository=repository or MaterialRepository(); self._cleaning_receipts={}; self._parse_locks=defaultdict(Lock)
    async def stream_original(self,project_id,filename,chunks,material_id=None,idempotency_key=None,base_version=None):
        if not project_id: raise AppException('PROJECT_REQUIRED','上传资料必须关联项目',400)
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',project_id): raise AppException('PROJECT_SCOPE_INVALID','项目标识不合法',400)
        display=Path(filename).name or 'material.txt'; mid=material_id or 'mat_'+uuid4().hex
        if not re.fullmatch(r'mat_[A-Za-z0-9_-]{8,80}',mid): raise AppException('MATERIAL_SCOPE_INVALID','资料标识不合法',400)
        versions=self.repository.list_versions(project_id,mid) if material_id else []; current=versions[-1].version if versions else 0
        if material_id and base_version is None: raise AppException('MATERIAL_VERSION_REQUIRED','替换资料必须提供base_version',422)
        if material_id and base_version != current: raise AppException('MATERIAL_VERSION_CONFLICT','资料版本已变化，请刷新后重试',409)
        version=current+1; root=(self.storage_root/project_id/mid/str(version)).resolve(); base=self.storage_root.resolve()
        if base not in root.parents: raise AppException('MATERIAL_SCOPE_INVALID','资料存储路径不合法',400)
        root.mkdir(parents=True,exist_ok=True); part=root/(uuid4().hex+'.part'); final=(root/(uuid4().hex+'-'+display)).resolve()
        if root not in final.parents: raise AppException('MATERIAL_SCOPE_INVALID','文件名不合法',400)
        digest=hashlib.sha256(); size=0
        committed=False
        try:
            with part.open('wb') as f:
                async for chunk in chunks:
                    if not isinstance(chunk,(bytes,bytearray)): raise AppException('UPLOAD_INVALID','上传数据块无效',400)
                    f.write(chunk); digest.update(chunk); size+=len(chunk)
            part.replace(final)
            item=MaterialVersion(project_id=project_id,material_id=mid,version=version,parent_version=version-1 if version>1 else None,original_sha256=digest.hexdigest(),original_path=str(final),filename=display,size_bytes=size,created_at=datetime.now(UTC))
            if idempotency_key:
                prior=self.repository.upload_replay(project_id,idempotency_key,item.original_sha256)
                if prior:
                    if final.exists(): final.unlink()
                    return prior
            if idempotency_key:
                atomic=getattr(self.repository,'save_version_with_upload_operation',None)
                saved=atomic(item,idempotency_key,item.original_sha256) if atomic else self.repository.save_version(item)
                if atomic is None: self.repository.record_upload_operation(project_id,idempotency_key,item.original_sha256,saved)
            else: saved=self.repository.save_version(item)
            committed=True
            return saved
        except Exception:
            if part.exists(): part.unlink()
            if not committed and final.exists(): final.unlink()
            raise
    def read_original(self,project_id,material_id,version):
        item=self.repository.get_version(project_id,material_id,version)
        path=Path(item.original_path).resolve(); root=self.storage_root.resolve()
        if root not in path.parents or not path.is_file():
            raise AppException('MATERIAL_ORIGINAL_MISSING','资料原件不存在，请重新上传',404)
        return path
    def parse_material(self,project_id,material_id,version,recognizer=None,failed_unit_ids=None):
        with self._parse_locks[(project_id,material_id,version)]:
            item=self.repository.get_version(project_id,material_id,version)
            if failed_unit_ids is None and item.parse_status in {'succeeded','partial'} and self.repository.get_units(project_id,material_id,version):
                return self.get_parse_manifest(project_id,material_id,version)
            return self._parse_material(project_id,material_id,version,recognizer,failed_unit_ids)
    def _parse_material(self,project_id,material_id,version,recognizer=None,failed_unit_ids=None):
        item=self.repository.get_version(project_id,material_id,version); self.repository.update_parse_status(project_id,material_id,version,'running')
        try:
            manifest=parse_source(Path(item.original_path),item.filename,recognizer)
            if failed_unit_ids:
                old={u.unit_id:u for u in self.repository.get_units(project_id,material_id,version)}
                manifest.units=[old.get(u.unit_id,u) if u.unit_id not in set(failed_unit_ids) and u.unit_id in old else u for u in manifest.units]
            manifest.material_id=material_id; manifest.version=version; self.repository.save_units(project_id,material_id,version,manifest.units); self.repository.update_parse_status(project_id,material_id,version,'succeeded' if manifest.coverage_complete else 'partial',manifest.readiness); return manifest
        except Exception:
            self.repository.update_parse_status(project_id,material_id,version,'failed','needs_review'); raise
    def get_parse_manifest(self,project_id,material_id,version,cursor=None):
        item=self.repository.get_version(project_id,material_id,version); units=self.repository.get_units(project_id,material_id,version)
        if not units: return self.parse_material(project_id,material_id,version)
        failed=sum(u.status=='failed' for u in units); pending=sum(u.status=='pending' for u in units); complete=not failed and not pending
        return ParseManifest(material_id=material_id,version=version,units_total=len(units),units_completed=len(units)-failed-pending,units_failed=failed,units_pending=pending,coverage_complete=complete,readiness='needs_review' if not complete or item.readiness=='needs_review' else 'readable',review_status=item.review_status,units=units,next_cursor=None)
    def preview_cleaning(self,project_id,material_id,base_version,operations):
        self.repository.get_version(project_id,material_id,base_version); ops=[x if isinstance(x,CleaningOperation) else CleaningOperation.model_validate(x) for x in operations]; digest=hashlib.sha256(json.dumps([x.model_dump(mode='json') for x in ops],sort_keys=True,ensure_ascii=False).encode()).hexdigest(); p=CleaningPreview(preview_id='prev_'+uuid4().hex,project_id=project_id,material_id=material_id,base_version=base_version,operations=ops,diff_digest=digest,expires_at=datetime.now(UTC)+timedelta(hours=1)); self.repository.save_preview(p); return p
    def apply_cleaning(self,project_id,material_id,preview_id,diff_digest,confirmed_operation_ids):
        p=self.repository.get_preview(project_id,preview_id)
        if p.material_id!=material_id: raise AppException('MATERIAL_SCOPE_INVALID','预览不属于当前资料',404)
        if p.diff_digest!=diff_digest: raise AppException('CLEANING_PREVIEW_INVALID','预览摘要不一致，请重新预览',409)
        if not {x.operation_id for x in p.operations}.issubset(set(confirmed_operation_ids)): raise AppException('CLEANING_CONFIRMATION_REQUIRED','请确认本次变更',422)
        cache_key=(project_id,material_id,preview_id)
        if cache_key in self._cleaning_receipts:
            return self._cleaning_receipts[cache_key]
        persisted=getattr(self.repository,'find_cleaning_receipt',lambda *_:None)(project_id,material_id,preview_id)
        if persisted is not None:
            self._cleaning_receipts[cache_key]=persisted
            return persisted
        if p.diff_digest!=diff_digest: raise AppException('CLEANING_PREVIEW_INVALID','预览摘要不一致，请重新预览',409)
        if not {x.operation_id for x in p.operations}.issubset(set(confirmed_operation_ids)): raise AppException('CLEANING_CONFIRMATION_REQUIRED','请确认本次变更',422)
        if p.material_id!=material_id: raise AppException('MATERIAL_SCOPE_INVALID','预览不属于当前资料',404)
        current=self.repository.get_version(project_id,material_id,p.base_version)
        latest=self.repository.list_versions(project_id,material_id)[-1].version
        if latest!=p.base_version: raise AppException('MATERIAL_VERSION_CONFLICT','资料版本已变化，请重新预览',409)
        units=[u.model_copy(deep=True) for u in self.repository.get_units(project_id,material_id,p.base_version)]
        matched=set()
        for op in p.operations:
            for unit in units:
                for region in unit.regions:
                    if f'{unit.locator}::{region.region_id}'==op.target_locator or (region.region_id==op.target_locator and sum(r.region_id==op.target_locator for u in units for r in u.regions)==1):
                        matched.add(op.operation_id)
                        if op.before not in (region.text, region.table_cells): raise AppException('CLEANING_SOURCE_CHANGED','原始内容已变化，请重新预览',409)
                        if region.kind=='table':
                            if not isinstance(op.after,list) or any(not isinstance(row,list) for row in op.after): raise AppException('CLEANING_OPERATION_INVALID','表格清洗结果必须为二维数组',422)
                            region.table_cells=[list(map(str,row)) for row in op.after]
                            region.text='\n'.join(' | '.join(row) for row in region.table_cells)
                        else: region.text=str(op.after)
        if matched!={x.operation_id for x in p.operations}: raise AppException('CLEANING_TARGET_NOT_FOUND','清洗定位不存在，请重新预览',422)
        new=current.model_copy(update={'version':current.version+1,'parent_version':current.version,'created_at':datetime.now(UTC),'readiness':'needs_review','review_status':'unreviewed'})
        receipt=CleaningReceipt(version=new.version,parent_version=current.version,applied_operation_ids=[x.operation_id for x in p.operations],event_id='evt_'+uuid4().hex)
        event=MaterialChangedEvent(event_id=receipt.event_id,project_id=project_id,material_id=material_id,old_version=current.version,new_version=new.version,changed_locators=[x.target_locator for x in p.operations],reason=f"cleaning:{preview_id}:{','.join(receipt.applied_operation_ids)}"); self.repository.atomic_version_event(new,units,event); self._cleaning_receipts[cache_key]=receipt; return receipt
    def undo_cleaning(self,project_id,material_id,base_version,restore_version):
        current=self.repository.get_version(project_id,material_id,base_version); source=self.repository.get_version(project_id,material_id,restore_version)
        new=current.model_copy(update={'version':current.version+1,'parent_version':current.version,'created_at':datetime.now(UTC),'readiness':'needs_review','review_status':'unreviewed','original_path':source.original_path,'original_sha256':source.original_sha256,'size_bytes':source.size_bytes})
        units=self.repository.get_units(project_id,material_id,restore_version); event=MaterialChangedEvent(event_id='evt_'+uuid4().hex,project_id=project_id,material_id=material_id,old_version=current.version,new_version=new.version,changed_locators=['*'],reason='cleaning-undo'); self.repository.atomic_version_event(new,units,event)
        return CleaningReceipt(version=new.version,parent_version=current.version,applied_operation_ids=[],event_id=event.event_id)
    def list_evidence(self,project_id,source_ids):
        out=[]
        for s in source_ids:
            version=self.repository.list_versions(project_id,s)[-1].version; units=self.repository.get_units(project_id,s,version)
            for unit in units:
                for region in unit.regions:
                    if region.text or region.table_cells:
                        locator=f'{unit.locator}::{region.region_id}'
                        data=dict(source_kind='material',source_id=s,source_version=version,locator=locator,excerpt=region.text[:300] or None,origin_kind='documented')
                        try: data['project_id']=project_id; out.append(EvidenceRef(**data))
                        except Exception: data.pop('project_id',None); out.append(EvidenceRef(**data))
        return out
    def resolve_evidence(self,project_id,refs):
        out=[]
        for ref in refs:
            if ref.source_kind!='material' or ref.origin_kind!='documented': raise AppException('EVIDENCE_ORIGIN_INVALID','资料来源性质由服务端确定，不能伪造',422)
            units=self.repository.get_units(project_id,ref.source_id,ref.source_version)
            found=[]
            for u in units:
                prefix=f'{u.locator}::'
                if ref.locator.startswith(prefix):
                    found.extend(r for r in u.regions if r.region_id==ref.locator[len(prefix):])
                elif ref.locator==u.locator:
                    found.extend(u.regions)
            if not found:
                # Legacy references used region_id alone; accept them only
                # when unique in the exact version to avoid cross-page drift.
                legacy=[r for u in units for r in u.regions if r.region_id==ref.locator]
                if len(legacy)==1: found=legacy
            if not found: raise AppException('EVIDENCE_NOT_FOUND','证据定位不存在',404)
            region=found[0]; text=region.text or '\n'.join(' | '.join(map(str,row)) for row in region.table_cells)
            out.append(EvidenceBlock(ref=ref,text=text,table_position=ref.locator))
        return out
material_service=MaterialService()
def resume_pending_material_parses():
    """Hook for application startup; persisted parse units are safe to retry."""
    return material_service.repository.pending_versions()
async def stream_original(*a,**k): return await material_service.stream_original(*a,**k)
def parse_material(*a,**k): return material_service.parse_material(*a,**k)
def list_evidence(project_id,source_ids): return material_service.list_evidence(project_id,source_ids)
def resolve_evidence(project_id,refs): return material_service.resolve_evidence(project_id,refs)
