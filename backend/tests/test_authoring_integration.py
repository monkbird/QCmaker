import pytest

from backend.app.core.errors import AppException
from backend.app.models.authoring import ChapterUpdate, EvidenceVerificationRequest, ScenarioCard
from backend.app.models.evidence import EvidenceRef
from backend.app.repositories import database
from backend.app.services.authoring import authoring_service as service
from backend.app.services.qc_paths import chapter_path


@pytest.fixture()
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'qc.sqlite3')
    database.init_database()
    return chapter_path()[0].chapter_id


@pytest.mark.asyncio
async def test_failed_generation_does_not_save_fake_success(store, monkeypatch):
    async def failed(*args, **kwargs): raise RuntimeError('provider failed')
    monkeypatch.setattr('backend.app.services.authoring.chat', failed)
    with pytest.raises(AppException):
        await service.generate_chapter('p', store, 0, 'op')
    assert service.list_chapters('p') == []


def test_fake_source_cannot_verify_a_chapter(store):
    service.update_chapter('p', store, ChapterUpdate(expected_revision=0, content_blocks=[{'kind':'text','text':'草稿'}]))
    ref = EvidenceRef(source_kind='user', source_id='nonexistent', source_version=1, locator='x', origin_kind='user_reported')
    with pytest.raises(AppException) as exc:
        service.verify_evidence('p', store, EvidenceVerificationRequest(expected_revision=1,evidence_state='verified',reviewer_id='author',basis=[ref]))
    assert exc.value.status_code == 404


def test_context_updates_are_versioned_and_path_context_persists(store):
    first = service.save_context(ScenarioCard(project_id='p', topic='标题', objective_source='directive'), 0)
    second = service.save_context(first.model_copy(update={'topic':'润色标题'}), 1)
    assert second.revision == 2 and service.get_context('p').objective_source == 'directive'
    with pytest.raises(AppException): service.save_context(first, 1)


def test_manual_save_replay_rejects_changed_input(store):
    request = ChapterUpdate(expected_revision=0,operation_id='manual-save',content_blocks=[{'kind':'text','text':'原稿'}])
    first = service.update_chapter('p',store,request)
    assert service.update_chapter('p',store,request) == first
    with pytest.raises(AppException) as exc:
        service.update_chapter('p',store,request.model_copy(update={'content_blocks':[{'kind':'text','text':'另稿'}]}))
    assert exc.value.code == 'OPERATION_CONFLICT'


@pytest.mark.asyncio
async def test_operation_replay_does_not_regenerate_and_rejects_other_input(store, monkeypatch):
    calls=[]
    async def generate(messages, role=None, **kwargs): calls.append(role);return '[{"kind":"text","text":"假设草稿"}]'
    monkeypatch.setattr('backend.app.services.authoring.chat', generate)
    a=await service.generate_chapter('p',store,0,'operation')
    b=await service.generate_chapter('p',store,0,'operation')
    assert a == b and calls == ['writer']
    with pytest.raises(AppException): await service.generate_chapter('p',chapter_path()[1].chapter_id,0,'operation')
