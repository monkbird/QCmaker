def test_no_excel_manual_authoring_review_and_export(client):
    context = client.get('/api/projects/draft/context').json()
    assert context['revision'] == 0
    context['topic'] = '提高排涝站巡检记录完整率'
    saved = client.put('/api/projects/draft/context?expected_revision=0', json=context)
    assert saved.status_code == 200, saved.text
    path = client.get('/api/projects/draft/chapters').json()['path']
    assert len(path) == 11
    chapter_id = path[0]['chapter_id']
    written = client.put(f'/api/projects/draft/chapters/{chapter_id}', json={'expected_revision':0,'content_blocks':[{'kind':'text','text':'小组资料待补','origin_kind':'pending'}],'content_state':'complete'})
    assert written.status_code == 200, written.text
    reviewed = client.post(f'/api/projects/draft/chapters/{chapter_id}/review',json={'expected_revision':1,'review_state':'approved','reviewer_id':'作者'})
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()['evidence_state'] == 'missing'
    request = {'project_id':'draft','chapter_revisions':{chapter_id:2},'operation_id':'export'}
    result = client.post('/api/ppt/generate-from-chapters',json=request)
    assert result.status_code == 200, result.text
    assert result.json()['payload']['preflight']['issues']
    assert client.post('/api/ppt/generate-from-chapters',json=request).json()['artifact_id'] == result.json()['artifact_id']
    download = client.get('/api/ppt/download/'+result.json()['payload']['file']['file_id'])
    assert download.status_code == 200 and download.content.startswith(b'PK')


def test_activity_edits_create_versions_without_cross_project_collisions(client):
    value={'event_id':'same-id','event_type':'implementation','title':'实施记录','expected_revision':0,'activity_start':'2026-08-01'}
    for project in ['one','two']:
        first=client.post(f'/api/projects/{project}/activities',json=value)
        assert first.status_code==200, first.text
    second=client.post('/api/projects/one/activities',json={**value,'expected_revision':1,'observations':'补充过程记录'})
    assert second.status_code==200,second.text
    assert second.json()['revision']==2
    assert len(client.get('/api/projects/two/activities').json()['activities'])==1


def test_scope_change_preview_preserves_history_and_marks_affected_chapter(client):
    p='/api/projects/changes'
    context=client.get(p+'/context').json()
    context=client.put(p+'/context?expected_revision=0',json=context).json()
    chapter_id=client.get(p+'/chapters').json()['path'][0]['chapter_id']
    assert client.put(p+'/chapters/'+chapter_id,json={'expected_revision':0,'content_blocks':[{'kind':'text','text':'旧版'}]}).status_code==200
    context['object_name']='新对象'
    assert client.put(p+'/context?expected_revision=1',json=context).status_code==409
    preview=client.post(p+'/changes/preview',json={'expected_revision':1,'context':context}).json()
    applied=client.post(p+'/changes/apply',json={'expected_revision':1,'context':context,'preview_id':preview['preview_id'],'chapter_ids':[chapter_id]})
    assert applied.status_code==200,applied.text
    assert client.get(p+f'/chapters/{chapter_id}/snapshot?revision=1').json()['stale'] is False
    assert client.get(p+f'/chapters/{chapter_id}/snapshot').json()['stale'] is True


def test_recommended_evidence_must_be_saved_before_fact_verification(client):
    project='/api/projects/evidence-review'
    chapter_id=client.get(project+'/chapters').json()['path'][0]['chapter_id']
    source={'source_id':'team-record','source_kind':'user','origin_kind':'user_reported','locator':'成员台账第1页','text':'小组成员和职责记录','expected_revision':0}
    assert client.post(project+'/sources',json=source).status_code==200
    recommended=client.get(project+f'/chapters/{chapter_id}/recommendations').json()['suggestions']
    assert len(recommended)==1 and recommended[0]['cannot_support']
    ref=recommended[0]['ref']
    assert client.put(project+f'/chapters/{chapter_id}',json={'expected_revision':0,'content_blocks':[{'kind':'text','text':'小组概况'}]}).status_code==200
    verification={'expected_revision':1,'evidence_state':'verified','reviewer_id':'作者','basis':[ref]}
    refused=client.post(project+f'/chapters/{chapter_id}/evidence-verification',json=verification)
    assert refused.status_code==422 and refused.json()['code']=='EVIDENCE_NOT_LINKED'
    assert client.put(project+f'/chapters/{chapter_id}',json={'expected_revision':1,'evidence_refs':[ref]}).status_code==200
    accepted=client.post(project+f'/chapters/{chapter_id}/evidence-verification',json={**verification,'expected_revision':2})
    assert accepted.status_code==200 and accepted.json()['evidence_state']=='verified'
    assert len(client.get(project+f'/chapters/{chapter_id}/history').json()['snapshots'])==3
    foreign='/api/projects/other-evidence-project'
    other_chapter=client.get(foreign+'/chapters').json()['path'][0]['chapter_id']
    assert client.get(foreign+f'/chapters/{other_chapter}/recommendations').json()['suggestions']==[]
