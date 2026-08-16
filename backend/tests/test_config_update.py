def test_config_update_persists_and_keeps_blank_secret(client, tmp_path, monkeypatch):
    from backend.app.core import config

    env_path = tmp_path / ".env"
    monkeypatch.setattr(config, "ENV_PATH", env_path)
    monkeypatch.setattr(config, "settings", config.Settings(_env_file=None, OPENAI_API_KEY="sk-original"))
    updated = config.update_settings({"OPENAI_API_KEY": "", "OPENAI_MODEL": "model-next", "MAX_BUDGET_USD": 3.5})
    assert updated.OPENAI_API_KEY == "sk-original"
    assert updated.OPENAI_MODEL == "model-next"
    assert updated.MAX_BUDGET_USD == 3.5
    assert "sk-original" in env_path.read_text(encoding="utf-8")
    assert updated.CONFIG_REVISION == 1
