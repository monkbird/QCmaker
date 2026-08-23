import pytest
from fastapi.testclient import TestClient

ISOLATED_SETTINGS = {
    "PROJECT_NAME": "Smart QC-Circle Generator",
    "OPENAI_API_KEY": None,
    "LLM_PROVIDER": "openai",
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "OPENAI_MODEL": "gpt-4o-mini",
    "EMBEDDING_MODEL": "text-embedding-3-small",
    "USE_LOCAL_LLM": False,
    "LOCAL_LLM_URL": "http://localhost:11434/v1",
    "LOCAL_LLM_MODEL": "llama3",
    "TAVILY_API_KEY": None,
    "MAX_BUDGET_USD": 5.0,
    "LLM_MAX_OUTPUT_TOKENS": 2048,
    "UNKNOWN_MODEL_RESERVE_USD": 0.25,
    "CORS_ORIGINS": "http://localhost:5173",
    "DATASET_TTL_HOURS": 24,
    "PPT_TTL_DAYS": 7,
    "CONFIG_REVISION": 0,
    "API_ACCESS_TOKEN": None,
    "RATE_LIMIT_PER_MINUTE": 10_000,
}


@pytest.fixture()
def isolated_settings(tmp_path, monkeypatch):
    """Isolate Settings from the developer's real .env / OS environment."""
    from backend.app.core import config as core_config

    for key in ISOLATED_SETTINGS:
        monkeypatch.delenv(key, raising=False)
    fresh = core_config.Settings(_env_file=None, **ISOLATED_SETTINGS)
    monkeypatch.setattr(core_config, "ENV_PATH", tmp_path / ".env")
    monkeypatch.setattr(core_config, "settings", fresh)
    return fresh


@pytest.fixture()
def isolated_storage(tmp_path, monkeypatch):
    """Redirect every on-disk artifact (db, ppt output, chroma) into tmp_path."""
    from backend.app.repositories import database
    from backend.app.services import ppt as ppt_service
    from backend.app.services.rag import rag_service

    data_dir = tmp_path / "data"
    monkeypatch.setattr(database, "DATA_DIR", data_dir)
    monkeypatch.setattr(database, "DB_PATH", data_dir / "qcmaker.sqlite3")
    monkeypatch.setattr(ppt_service, "OUTPUT_DIR", tmp_path / "generated_ppts")
    monkeypatch.setattr(ppt_service, "TEMPLATE_DIR", tmp_path / "templates")
    monkeypatch.setattr(rag_service, "persist_directory", str(tmp_path / "chroma_db"))
    return tmp_path


@pytest.fixture()
def client(tmp_path, isolated_settings, isolated_storage):
    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client
