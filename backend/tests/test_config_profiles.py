import json

from backend.app.models.config_profiles import ConfigDraft, ModelBinding, RuntimeSnapshot, ServiceDraft


def _db(tmp_path, monkeypatch):
    from backend.app.repositories import database
    monkeypatch.setattr(database, "DATA_DIR", tmp_path)
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "db.sqlite3")
    database.init_database()


def test_config_draft_rejects_unknown_binding():
    import pytest
    with pytest.raises(ValueError):
        ConfigDraft(name="x", services=[], default_model=ModelBinding(service_id="missing", model="m"))


def test_runtime_snapshot_clone_isolated():
    draft = ConfigDraft(name="x", services=[ServiceDraft(service_id="p", provider="custom", base_url="https://example.com/v1")])
    snap = RuntimeSnapshot(config_revision=2, draft=draft)
    clone = snap.clone()
    clone.draft.name = "changed"
    assert snap.draft.name == "x"


def test_profile_routes_hide_secret(client):
    before = client.get("/api/config/profiles").json()
    payload = {"expected_revision": before["config_revision"], "draft": {"name": "x", "services": [{"service_id": "p", "provider": "custom", "base_url": "https://example.com/v1", "api_key": "test-secret"}], "roles": {"topic": {"service_id": "p", "model": "m"}}}}
    response = client.post("/api/config/profiles/save", json=payload)
    assert response.status_code == 200
    assert "test-secret" not in response.text
    listing = client.get("/api/config/profiles").json()
    assert listing["active_profile_id"] == response.json()["profile_id"]
    assert "test-secret" not in json.dumps(listing)


def test_new_key_does_not_mutate_sibling_and_endpoint_binding_is_checked(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    from backend.app.repositories.config_profile_repository import save_and_activate, active_snapshot
    first = ConfigDraft(name="one", services=[ServiceDraft(service_id="p", provider="custom", base_url="https://one/v1", api_key="first")], default_model=ModelBinding(service_id="p", model="m"))
    from backend.app.models.config_profiles import ProfileSaveRequest
    one = save_and_activate(ProfileSaveRequest(expected_revision=0, draft=first))
    second = ConfigDraft(name="two", services=[ServiceDraft(service_id="p", provider="custom", base_url="https://two/v1", api_key="second")], default_model=ModelBinding(service_id="p", model="m"))
    save_and_activate(ProfileSaveRequest(expected_revision=one.config_revision, draft=second))
    snap = active_snapshot()
    assert snap and snap.draft.services[0].api_key.get_secret_value() == "second"


def test_active_profile_target_changes_after_switch(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    from backend.app.repositories.config_profile_repository import save_and_activate, activate, active_snapshot
    from backend.app.models.config_profiles import ProfileSaveRequest
    from backend.app.services.model_roles import resolve_role_target
    a = save_and_activate(ProfileSaveRequest(expected_revision=0, draft=ConfigDraft(name="a", services=[ServiceDraft(service_id="p", provider="custom", base_url="https://a/v1", api_key="a")], default_model=ModelBinding(service_id="p", model="ma"))))
    b = save_and_activate(ProfileSaveRequest(expected_revision=a.config_revision, draft=ConfigDraft(name="b", services=[ServiceDraft(service_id="q", provider="custom", base_url="https://b/v1", api_key="b")], default_model=ModelBinding(service_id="q", model="mb"))))
    activate(a.profile_id, b.config_revision)
    assert resolve_role_target(None, snapshot=active_snapshot()).model == "ma"


def test_legacy_migration_keeps_all_service_and_search_credentials(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    import json
    from backend.app.core.config import Settings
    from backend.app.repositories.config_profile_repository import migrate_legacy, active_snapshot
    settings = Settings(_env_file=None, OPENAI_API_KEY="main", ROLE_MODELS=json.dumps({"critic":"deepseek|dm"}), PROVIDER_CREDENTIALS=json.dumps({"deepseek":{"api_key":"deep"}}), TAVILY_API_KEY="tv")
    migrate_legacy(settings)
    snap = active_snapshot()
    assert snap and {s.api_key.get_secret_value() for s in snap.draft.services} == {"main", "deep"}
    assert snap.draft.search and snap.draft.search.api_key.get_secret_value() == "tv"


def test_legacy_migration_does_not_replace_existing_active_profile(tmp_path, monkeypatch):
    _db(tmp_path, monkeypatch)
    from backend.app.core.config import Settings
    from backend.app.repositories.config_profile_repository import migrate_legacy, save_and_activate, active_snapshot
    from backend.app.models.config_profiles import ProfileSaveRequest
    saved = save_and_activate(ProfileSaveRequest(expected_revision=0, draft=ConfigDraft(
        name="用户方案", services=[ServiceDraft(service_id="svc", provider="custom", base_url="https://example.com/v1", api_key="saved")],
        default_model=ModelBinding(service_id="svc", model="saved-model"))))
    migrate_legacy(Settings(_env_file=None, OPENAI_API_KEY="legacy", OPENAI_MODEL="legacy-model"))
    snap = active_snapshot()
    assert snap and snap.draft.name == "用户方案"
    assert snap.config_revision == saved.config_revision
