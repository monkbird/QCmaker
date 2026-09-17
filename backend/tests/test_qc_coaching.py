import json

import pytest

from backend.app.models.authoring import ChapterUpdate
from backend.app.repositories import database
from backend.app.services.authoring import authoring_service
from backend.app.services.qc_paths import chapter_path


def test_topic_mode_keeps_an_intended_topic_in_selection_stage():
    from backend.app.services.qc_coaching import topic_mode
    assert topic_mode('我没想法', []) == 'explore'
    assert topic_mode('我想写一篇关于清淤土提升水稻产量的QC', []) == 'justify'
    assert topic_mode('你先给我合理的选择原因', [{'role': 'user', 'content': '提高低产田水稻产量'}]) == 'justify'
    assert topic_mode('我想重新找方向，暂时没想法', [{'role': 'user', 'content': '提高低产田水稻产量'}]) == 'explore'


@pytest.mark.asyncio
async def test_generation_receives_prior_chapter_bottleneck_but_not_future_or_other_project(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'qc.sqlite3')
    database.init_database()
    path = {p.slug: p for p in chapter_path()}
    def save(project, slug, text):
        return authoring_service.update_chapter(project, path[slug].chapter_id, ChapterUpdate(expected_revision=0, content_blocks=[{'kind': 'text', 'text': text, 'origin_kind': 'simulation'}]))
    previous = save('p', 'current_situation', '最大症结：土壤肥力低；模拟频次108/150，占72%。')
    save('other', 'current_situation', '其他项目秘密')
    save('p', 'countermeasure', '未来对策不能倒推成已确认原因')
    calls = []
    async def fake_chat(messages, **kwargs):
        calls.append(messages)
        return json.dumps([{'kind': 'text', 'text': '围绕肥力低列末端因素', 'origin_kind': 'simulation'}])
    monkeypatch.setattr('backend.app.services.authoring.chat', fake_chat)
    result = await authoring_service.generate_chapter('p', path['cause_analysis'].chapter_id, 0, 'coaching-test')
    prompt = calls[-1][-1]['content']
    assert '最大症结：土壤肥力低' in prompt
    assert 'simulation' in prompt
    assert '其他项目秘密' not in prompt
    assert '未来对策不能倒推' not in prompt
    assert result.upstream_versions['chapter:' + previous.chapter_id] == previous.revision
    edited = authoring_service.update_chapter('p', result.chapter_id, ChapterUpdate(expected_revision=result.revision, content_blocks=result.content_blocks))
    assert edited.upstream_versions == result.upstream_versions
    authoring_service.update_chapter('p', previous.chapter_id, ChapterUpdate(expected_revision=previous.revision, content_blocks=[{'kind':'text','text':'症结更新'}]))
    refreshed = authoring_service.get_snapshot('p', result.chapter_id)
    assert refreshed.stale and any('前置章节' in reason for reason in refreshed.stale_reasons)


def test_rich_generated_blocks_preserve_data_and_reject_invalid_chart_values():
    from backend.app.services.authoring import validate_generated_blocks
    blocks = [
        {'kind':'table','title':'选题差距','columns':['对象','亩产'],'rows':[{'对象':'现状','亩产':336}]},
        {'kind':'chart','chart_type':'bar','rows':[{'label':'现状','value':336},{'label':'参照','value':380}]},
    ]
    assert validate_generated_blocks(blocks)[0]['kind'] == 'table'
    with pytest.raises(ValueError):
        validate_generated_blocks([{'kind':'chart','chart_type':'bar','rows':[{'label':'现状','value':float('nan')}]}])
    with pytest.raises(ValueError):
        validate_generated_blocks([{'kind':'chart','chart_type':'pareto','rows':[{'label':'症结','value':-1}]}])
