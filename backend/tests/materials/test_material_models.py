from backend.app.models.materials import CleaningOperation,ParseManifest

def test_manifest_counts_and_cleaning_operation_are_structured():
    op=CleaningOperation(operation_id='op1',category='data',target_locator='sheet1!A1',before='10%',after=.1,reason='单位转换',risk='high')
    assert op.after==.1 and op.risk=='high'
    m=ParseManifest(material_id='m1',version=1,units_total=0,units_completed=0,units_failed=0,units_pending=0,coverage_complete=False,readiness='unread',review_status='unreviewed')
    assert m.units==[]
