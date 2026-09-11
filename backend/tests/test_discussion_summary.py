import asyncio
import json

import pytest

from backend.app.core.errors import AppException
from backend.app.repositories.database import transaction
from backend.app.services import discussion_session as service


def prepare_finish(client, history=None):
    data = client.post('/api/data/upload', files={'file': ('data.csv', b'x,y\nA,10\n', 'text/csv')}).json()
    client.post('/api/data/confirm', json={'dataset_id': data['dataset_id'], 'revision': 0})
    service.accept_command(dict(type='start', session_id='summary', client_message_id='start', topic='test', dataset_id=data['dataset_id'], revision=0, project_id='p'))
    with transaction(immediate=True) as db:
        state = json.loads(db.execute('SELECT state_json FROM discussion_sessions WHERE session_id=?', ('summary',)).fetchone()[0])
        state['history'] = history or []
        db.execute('UPDATE discussion_sessions SET state_json=?,status=? WHERE session_id=?', (json.dumps(state), 'round_done', 'summary'))
        db.execute("UPDATE discussion_commands SET status='completed' WHERE session_id=?", ('summary',))
    command = dict(type='finish', session_id='summary', client_message_id='finish')
    service.accept_command(command)
    return command


@pytest.mark.parametrize('invalid', ['not JSON', '抱歉，我无法完成该请求。', '{"problem": "missing fields"}', '{"problem":"x","root_causes":[],"countermeasures":[],"summary":"   "}'])
def test_invalid_summary_is_recoverable_without_fabricating_results(client, monkeypatch, invalid):
    history = [{'agent': 'user', 'content': '已确认的重要事实'}]
    command = prepare_finish(client, history)
    calls = []

    async def chat(messages, role=None):
        calls.append(role)
        if len(calls) == 1:
            return invalid
        return json.dumps(dict(problem='test', root_causes=[], countermeasures=[], summary='已确认的重要事实'))

    monkeypatch.setattr(service, 'chat', chat)
    events = asyncio.run(service.execute(command))
    assert [event['type'] for event in events] == ['error']
    assert events[0]['recoverable'] is True
    assert events[0]['error']['code'] == 'DISCUSSION_SUMMARY_INVALID'
    with transaction() as db:
        row = db.execute('SELECT status,state_json FROM discussion_sessions WHERE session_id=?', ('summary',)).fetchone()
        assert row['status'] == 'round_error'
        assert json.loads(row['state_json'])['history'] == history
    service.accept_command(dict(type='recover', session_id='summary', client_message_id='recover'))
    pending = service.pending_commands('summary')
    assert len(pending) == 1
    recovered = asyncio.run(service.execute(pending[0]))
    assert [event['type'] for event in recovered] == ['finished']
    assert recovered[0]['summary']['summary'] == '已确认的重要事实'
    assert calls == ['writer', 'writer']
    with transaction() as db:
        state = json.loads(db.execute('SELECT state_json FROM discussion_sessions WHERE session_id=?', ('summary',)).fetchone()[0])
        assert state['round'] == 1


def test_final_summary_includes_early_confirmed_facts_and_complete_history(client, monkeypatch):
    history = [{'agent': 'user', 'content': '已确认唯一根因：南侧闸门传感器偏移，排除电源故障'}]
    history += [{'agent': 'analyst', 'content': f'后续讨论事项 {index}'} for index in range(20)]
    command = prepare_finish(client, history)
    contexts = []

    async def chat(messages, role=None):
        contexts.append(messages[-1]['content'])
        return json.dumps(dict(problem='test', root_causes=[], countermeasures=[], summary='done'))

    monkeypatch.setattr(service, 'chat', chat)
    events = asyncio.run(service.execute(command))
    assert events[-1]['type'] == 'finished'
    assert len(contexts) == 1
    for item in history:
        assert item['content'] in contexts[0]


def test_writer_provider_failure_preserves_history_without_automatic_retries(client, monkeypatch):
    history = [{'agent': 'user', 'content': '已确认的调查结论'}]
    command = prepare_finish(client, history)
    calls = []

    async def chat(messages, role=None):
        calls.append(role)
        raise AppException('LLM_REQUEST_FAILED', 'Provider context limit exceeded', 502)

    monkeypatch.setattr(service, 'chat', chat)
    events = asyncio.run(service.execute(command))
    assert calls == ['writer']
    assert [event['type'] for event in events] == ['error']
    assert events[0]['error']['code'] == 'LLM_REQUEST_FAILED'
    assert events[0]['recoverable'] is True
    with transaction() as db:
        state = json.loads(db.execute('SELECT state_json FROM discussion_sessions WHERE session_id=?', ('summary',)).fetchone()[0])
        assert state['history'] == history
