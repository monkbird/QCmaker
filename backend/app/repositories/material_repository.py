from __future__ import annotations
import json
from datetime import UTC, datetime
from backend.app.core.errors import AppException
from backend.app.models.materials import *
from backend.app.repositories.database import connect, transaction

def _now(): return datetime.now(UTC)
def _dump(v): return json.dumps(v.model_dump(mode='json') if hasattr(v,'model_dump') else v, ensure_ascii=False, default=str)

class MaterialRepository:
    def update_parse_status(self,project_id,material_id,version,status,readiness=None):
        with transaction(immediate=True) as db:
            row=db.execute('SELECT v.metadata_json FROM material_versions v JOIN materials m ON m.material_id=v.material_id WHERE m.project_id=? AND v.material_id=? AND v.version=?',(project_id,material_id,version)).fetchone()
            if not row: raise AppException('MATERIAL_NOT_FOUND','资料版本不存在',404)
            meta=json.loads(row['metadata_json']); meta['parse_status']=status
            if readiness: meta['readiness']=readiness
            db.execute('UPDATE material_versions SET metadata_json=? WHERE material_id=? AND version=?',(json.dumps(meta,ensure_ascii=False),material_id,version))
    def pending_versions(self):
        with transaction(immediate=True) as db:
            db.execute("UPDATE material_versions SET metadata_json=json_set(metadata_json, '$.parse_status', 'queued') WHERE json_extract(metadata_json, '$.parse_status')='running'")
        db=connect()
        try: rows=db.execute("SELECT m.project_id,v.material_id,v.version,v.metadata_json FROM materials m JOIN material_versions v ON v.material_id=m.material_id").fetchall()
        finally: db.close()
        out=[]
        for r in rows:
            if json.loads(r['metadata_json']).get('parse_status') in {'queued','running','partial'}: out.append((r['project_id'],r['material_id'],r['version']))
        return out
    def find_cleaning_receipt(self, project_id, material_id, preview_id):
        db=connect()
        try:
            row=db.execute('SELECT * FROM material_events WHERE project_id=? AND material_id=? AND reason LIKE ?', (project_id, material_id, f'cleaning:{preview_id}:%')).fetchone()
        finally: db.close()
        if not row:
            return None
        encoded = row['reason'].split(':', 2)[2]
        ids = encoded.split(',') if encoded else []
        return CleaningReceipt(version=row['new_version'], parent_version=row['old_version'], applied_operation_ids=ids, event_id=row['event_id'])
    def upload_replay(self, project_id, key, request_hash):
        db=connect()
        try:
            row=db.execute('SELECT request_hash,result_json FROM material_upload_operations WHERE project_id=? AND idempotency_key=?',(project_id,key)).fetchone()
        finally: db.close()
        if not row: return None
        if row['request_hash']!=request_hash: raise AppException('IDEMPOTENCY_CONFLICT','幂等键已用于其他上传内容',409)
        return MaterialVersion.model_validate(json.loads(row['result_json'])) if row['result_json'] else None
    def record_upload_operation(self,project_id,key,request_hash,item):
        with transaction(immediate=True) as db: db.execute('INSERT OR REPLACE INTO material_upload_operations(project_id,idempotency_key,request_hash,material_id,result_json,created_at) VALUES(?,?,?,?,?,?)',(project_id,key,request_hash,item.material_id,_dump(item),_now().isoformat()))
    def get_version(self, project_id: str, material_id: str, version: int) -> MaterialVersion:
        db=connect()
        try:
            row=db.execute('SELECT m.project_id,m.name,v.* FROM materials m JOIN material_versions v ON v.material_id=m.material_id WHERE m.project_id=? AND m.material_id=? AND v.version=?',(project_id,material_id,version)).fetchone()
        finally: db.close()
        if not row: raise AppException('MATERIAL_NOT_FOUND','资料版本不存在',404)
        meta=json.loads(row['metadata_json']); return MaterialVersion(project_id=project_id,material_id=material_id,version=version,original_path=row['original_path'],**meta)
    def list_materials(self, project_id):
        db=connect()
        try: rows=db.execute('SELECT * FROM materials WHERE project_id=? ORDER BY updated_at DESC',(project_id,)).fetchall()
        finally: db.close()
        return [{'material_id':r['material_id'],'filename':r['name'],'version':r['current_version']} for r in rows]
    def list_versions(self, project_id, material_id):
        db=connect()
        try:
            if not db.execute('SELECT 1 FROM materials WHERE project_id=? AND material_id=?',(project_id,material_id)).fetchone(): raise AppException('MATERIAL_NOT_FOUND','资料不存在',404)
            rows=db.execute('SELECT * FROM material_versions WHERE material_id=? ORDER BY version',(material_id,)).fetchall()
        finally: db.close()
        return [MaterialVersion(project_id=project_id,material_id=material_id,version=r['version'],original_path=r['original_path'],**json.loads(r['metadata_json'])) for r in rows]
    def save_version(self, item: MaterialVersion):
        with transaction(immediate=True) as db:
            exists=db.execute('SELECT 1 FROM materials WHERE project_id=? AND material_id=?',(item.project_id,item.material_id)).fetchone()
            if not exists: db.execute('INSERT INTO materials(material_id,project_id,name,current_version,created_at,updated_at) VALUES(?,?,?,?,?,?)',(item.material_id,item.project_id,item.filename,item.version,item.created_at.isoformat(),item.created_at.isoformat()))
            else:
                current=db.execute('SELECT current_version FROM materials WHERE project_id=? AND material_id=?',(item.project_id,item.material_id)).fetchone()[0]
                if current != (item.parent_version or 0): raise AppException('MATERIAL_VERSION_CONFLICT','资料版本已变化，请刷新后重试',409)
            db.execute('INSERT INTO material_versions(material_id,version,original_path,metadata_json,created_at) VALUES(?,?,?,?,?)',(item.material_id,item.version,item.original_path,_dump(item.model_dump(exclude={'project_id','material_id','version','original_path'})),item.created_at.isoformat()))
            db.execute('UPDATE materials SET current_version=?,name=?,updated_at=? WHERE material_id=? AND project_id=?',(item.version,item.filename,item.created_at.isoformat(),item.material_id,item.project_id))
        return item
    def save_version_with_upload_operation(self,item,key,request_hash):
        with transaction(immediate=True) as db:
            prior=db.execute('SELECT request_hash,result_json FROM material_upload_operations WHERE project_id=? AND idempotency_key=?',(item.project_id,key)).fetchone()
            if prior:
                if prior['request_hash'] != request_hash: raise AppException('IDEMPOTENCY_CONFLICT','幂等键已用于其他上传内容',409)
                return MaterialVersion.model_validate(json.loads(prior['result_json'])) if prior['result_json'] else None
            exists=db.execute('SELECT current_version FROM materials WHERE project_id=? AND material_id=?',(item.project_id,item.material_id)).fetchone()
            if not exists:
                db.execute('INSERT INTO materials(material_id,project_id,name,current_version,created_at,updated_at) VALUES(?,?,?,?,?,?)',(item.material_id,item.project_id,item.filename,item.version,item.created_at.isoformat(),item.created_at.isoformat()))
            elif exists[0] != (item.parent_version or 0):
                raise AppException('MATERIAL_VERSION_CONFLICT','资料版本已变化，请刷新后重试',409)
            db.execute('INSERT INTO material_versions(material_id,version,original_path,metadata_json,created_at) VALUES(?,?,?,?,?)',(item.material_id,item.version,item.original_path,_dump(item.model_dump(exclude={'project_id','material_id','version','original_path'})),item.created_at.isoformat()))
            db.execute('UPDATE materials SET current_version=?,name=?,updated_at=? WHERE material_id=? AND project_id=?',(item.version,item.filename,item.created_at.isoformat(),item.material_id,item.project_id))
            db.execute('INSERT INTO material_upload_operations(project_id,idempotency_key,request_hash,material_id,result_json,created_at) VALUES(?,?,?,?,?,?)',(item.project_id,key,request_hash,item.material_id,_dump(item),_now().isoformat()))
        return item
    def save_units(self, project_id, material_id, version, units):
        with transaction(immediate=True) as db:
            for unit in units: db.execute('INSERT OR REPLACE INTO material_parse_units(material_id,version,unit_id,locator,status,content_json,error) VALUES(?,?,?,?,?,?,?)',(material_id,version,unit.unit_id,unit.locator,unit.status,_dump(unit.model_dump()),'\n'.join(unit.issues) or None))
    def get_units(self, project_id, material_id, version):
        self.get_version(project_id,material_id,version); db=connect()
        try: rows=db.execute('SELECT content_json FROM material_parse_units WHERE material_id=? AND version=? ORDER BY rowid',(material_id,version)).fetchall()
        finally: db.close()
        return [ParseUnit.model_validate(json.loads(r['content_json'])) for r in rows if r['content_json']]
    def save_preview(self, preview):
        with transaction(immediate=True) as db: db.execute('INSERT OR REPLACE INTO material_cleaning_previews VALUES(?,?,?,?,?,?,?,?)',(preview.preview_id,preview.project_id,preview.material_id,preview.base_version,_dump([x.model_dump() for x in preview.operations]),preview.diff_digest,preview.expires_at.isoformat(),_now().isoformat()))
    def get_preview(self, project_id, preview_id):
        db=connect()
        try: row=db.execute('SELECT * FROM material_cleaning_previews WHERE project_id=? AND preview_id=?',(project_id,preview_id)).fetchone()
        finally: db.close()
        if not row: raise AppException('CLEANING_PREVIEW_NOT_FOUND','清洗预览不存在或已过期',404)
        p=CleaningPreview(preview_id=row['preview_id'],project_id=project_id,material_id=row['material_id'],base_version=row['base_version'],operations=[CleaningOperation.model_validate(x) for x in json.loads(row['operations_json'])],diff_digest=row['diff_digest'],expires_at=datetime.fromisoformat(row['expires_at']))
        if p.expires_at <= _now(): raise AppException('CLEANING_PREVIEW_EXPIRED','清洗预览已过期，请重新预览',409)
        return p
    def add_event(self,event):
        with transaction(immediate=True) as db: db.execute('INSERT INTO material_events VALUES(?,?,?,?,?,?,?,?)',(event.event_id,event.project_id,event.material_id,event.old_version,event.new_version,_dump(event.changed_locators),event.reason,_now().isoformat()))
    def atomic_version_event(self,item,units,event):
        with transaction(immediate=True) as db:
            db.execute('INSERT INTO material_versions(material_id,version,original_path,metadata_json,created_at) VALUES(?,?,?,?,?)',(item.material_id,item.version,item.original_path,_dump(item.model_dump(exclude={'project_id','material_id','version','original_path'})),item.created_at.isoformat()))
            cur=db.execute('UPDATE materials SET current_version=?,name=?,updated_at=? WHERE material_id=? AND project_id=? AND current_version=?',(item.version,item.filename,item.created_at.isoformat(),item.material_id,item.project_id,item.parent_version))
            if cur.rowcount!=1: raise AppException('MATERIAL_VERSION_CONFLICT','资料版本已变化，请重新预览',409)
            for unit in units: db.execute('INSERT OR REPLACE INTO material_parse_units(material_id,version,unit_id,locator,status,content_json,error) VALUES(?,?,?,?,?,?,?)',(item.material_id,item.version,unit.unit_id,unit.locator,unit.status,_dump(unit.model_dump()),'\n'.join(unit.issues) or None))
            db.execute('INSERT INTO material_events VALUES(?,?,?,?,?,?,?,?)',(event.event_id,event.project_id,event.material_id,event.old_version,event.new_version,_dump(event.changed_locators),event.reason,_now().isoformat()))
    def pending_events(self, project_id):
        db=connect()
        try: rows=db.execute('SELECT e.* FROM material_events e WHERE e.project_id=? ORDER BY e.created_at',(project_id,)).fetchall()
        finally: db.close()
        return [MaterialChangedEvent(event_id=r['event_id'],project_id=r['project_id'],material_id=r['material_id'],old_version=r['old_version'],new_version=r['new_version'],changed_locators=json.loads(r['changed_locators_json']),reason=r['reason']) for r in rows]

material_repository=MaterialRepository()
