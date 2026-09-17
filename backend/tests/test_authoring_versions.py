def test_repository_save_and_idempotent_generation(isolated_storage, isolated_settings):
    from backend.app.repositories.database import init_database
    from backend.app.repositories.authoring_repository import authoring_repository
    from backend.app.models.evidence import ChapterSnapshot
    init_database()
    first = authoring_repository.save_snapshot(ChapterSnapshot(project_id='p',chapter_id='overview',path_version='v',revision=1),0,'op1')
    again = authoring_repository.get_operation_snapshot('p','op1')
    assert first.revision == again.revision == 1
    assert first.model_dump() == again.model_dump()
