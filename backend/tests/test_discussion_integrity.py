import asyncio

import pytest

from backend.app.core.errors import AppException
from backend.app.services import discussion_session as service


def dataset(client):
    data = client.post('/api/data/upload', files={'file': ('data.csv', b'x,y\nA,10\nB,30\n', 'text/csv')}).json()
    client.post('/api/data/confirm', json={'dataset_id': data['dataset_id'], 'revision': 0})
    return data['dataset_id']


def test_start_requires_confirmed_dataset(client):
    with pytest.raises(AppException):
        service.accept_command(dict(type='start', session_id='missing', client_message_id='c', topic='x', data_summary='fake'))


def test_real_values_and_completed_command_claim(client, monkeypatch):
    command = dict(type='start', session_id='real', client_message_id='c', topic='x', dataset_id=dataset(client), revision=0, project_id='p')
    service.accept_command(command)
    contexts=[]
    async def chat(messages, role=None):
        contexts.append(messages[-1]['content'])
        return '["analyst"]' if 'JSON数组' in messages[-1]['content'] else 'ok'
    monkeypatch.setattr(service, 'chat', chat)
    asyncio.run(service.execute(command))
    count=len(contexts)
    assert any('30' in context and '10' in context for context in contexts)
    asyncio.run(service.execute(command))
    assert len(contexts)==count
    events,_=service.accept_command(dict(type='resume', session_id='real', client_message_id='r', last_event_seq=0))
    assert events[-1]['session_status']=='round_done'


def test_streams_before_round_completes_and_accepts_finish(client, monkeypatch):
    import threading
    blocked = threading.Event()
    release = threading.Event()
    async def chat(messages, role=None):
        if 'JSON数组' in messages[-1]['content']: return '["analyst"]'
        if role == 'analyst':
            blocked.set()
            await asyncio.to_thread(release.wait, 5)
        if role == 'writer': return '{"problem":"x","root_causes":[],"countermeasures":[],"summary":"done"}'
        return 'ok'
    monkeypatch.setattr(service, 'chat', chat)
    command = dict(type='start', session_id='stream', client_message_id='c', topic='x', dataset_id=dataset(client), revision=0, project_id='p')
    try:
        with client.websocket_connect('/api/discussion/ws') as ws:
            ws.send_json(command)
            assert ws.receive_json()['type'] == 'ack'
            assert ws.receive_json()['agent'] == 'moderator'
            assert blocked.wait(1)
            ws.send_json(dict(type='finish', session_id='stream', client_message_id='f'))
            assert ws.receive_json()['type'] == 'ack'
            assert not release.is_set()
            release.set()
            remaining = [ws.receive_json() for _ in range(3)]
            assert [event['type'] for event in remaining] == ['agent_message', 'round_done', 'finished']
    finally:
        release.set()


def test_concurrent_finish_is_claimed_once_and_resume_has_terminal_snapshot(client, monkeypatch):
    calls=[]
    async def chat(messages, role=None):
        calls.append(role)
        await asyncio.sleep(0.01)
        return '{"problem":"x","root_causes":[],"countermeasures":[],"summary":"done"}'
    monkeypatch.setattr(service, 'chat', chat)
    service.accept_command(dict(type='start', session_id='terminal', client_message_id='s', topic='x', dataset_id=dataset(client), revision=0, project_id='p'))
    command=dict(type='finish', session_id='terminal', client_message_id='f')
    service.accept_command(command)
    async def run(): return await asyncio.gather(service.execute(command),service.execute(command))
    events=asyncio.run(run())
    assert calls==['writer']
    assert len([e for group in events for e in group if e['type']=='finished'])==1
    replay,_=service.accept_command(dict(type='resume',session_id='terminal',client_message_id='r',last_event_seq=3))
    assert replay[-1]['session_status']=='finished'


def test_start_rejects_stale_or_unconfirmed_data(client):
    dataset_id=dataset(client)
    with pytest.raises(AppException, match='版本'):
        service.accept_command(dict(type='start',session_id='stale',client_message_id='s',topic='x',dataset_id=dataset_id,revision=1,project_id='p'))
    from backend.app.repositories.database import transaction
    with transaction(immediate=True) as db:
        db.execute('UPDATE datasets SET confirmed_revision=NULL WHERE dataset_id=?',(dataset_id,))
    with pytest.raises(AppException, match='版本'):
        service.accept_command(dict(type='start',session_id='unconfirmed',client_message_id='s',topic='x',dataset_id=dataset_id,revision=0,project_id='p'))
