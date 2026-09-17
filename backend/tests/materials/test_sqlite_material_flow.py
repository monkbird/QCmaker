import asyncio
from pathlib import Path
import pytest
from backend.app.models.materials import CleaningOperation

@pytest.mark.asyncio
async def test_sqlite_upload_parse_and_evidence(tmp_path,monkeypatch):
    import backend.app.repositories.database as database
    monkeypatch.setattr(database,'DATA_DIR',tmp_path/'db'); monkeypatch.setattr(database,'DB_PATH',tmp_path/'db'/'x.sqlite3'); database.init_database()
    from backend.app.repositories.material_repository import MaterialRepository
    from backend.app.services.materials import MaterialService
    service=MaterialService(tmp_path/'store',MaterialRepository())
    async def chunks(): yield 'a,b\n1,2\n'.encode()
    item=await service.stream_original('p1','x.csv',chunks(),idempotency_key='one')
    manifest=service.parse_material('p1',item.material_id,1); assert manifest.coverage_complete
    refs=service.list_evidence('p1',[item.material_id]); assert refs
    assert service.resolve_evidence('p1',refs)[0].text
    region=manifest.units[0].regions[0]
    before=region.table_cells if region.kind=='table' else region.text
    after=[['a','b'],['3','4']] if region.kind=='table' else 'updated'
    locator=f'{manifest.units[0].locator}::{region.region_id}'
    preview=service.preview_cleaning('p1',item.material_id,1,[CleaningOperation(operation_id='change',category='data',target_locator=locator,before=before,after=after,reason='核对')])
    receipt=service.apply_cleaning('p1',item.material_id,preview.preview_id,preview.diff_digest,['change'])
    assert receipt.version==2
    # Replay remains stable after reconstructing the service, using persisted events.
    rebuilt=MaterialService(tmp_path/'store',MaterialRepository())
    assert rebuilt.apply_cleaning('p1',item.material_id,preview.preview_id,preview.diff_digest,['change'])==receipt
    undone=rebuilt.undo_cleaning('p1',item.material_id,2,1)
    assert undone.version==3
    restored=rebuilt.repository.get_units('p1',item.material_id,3)[0].regions[0]
    assert (restored.table_cells if restored.kind=='table' else restored.text)==before
