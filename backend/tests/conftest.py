import os
import socket
import tempfile
from pathlib import Path

# Set before test-module imports: no test should ever read the developer's .env.
os.environ['QCMAKER_ENV_FILE'] = str(Path(tempfile.gettempdir()) / 'qcmaker-tests-nonexistent' / '.env')

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
    "ROLE_MODELS": "{}",
    "PROVIDER_CREDENTIALS": "{}",
}


@pytest.fixture(autouse=True)
def offline_network(monkeypatch):
    def resolve(host, port, *args, **kwargs):
        import ipaddress
        try:
            address = str(ipaddress.ip_address(host))
        except ValueError:
            address = '127.0.0.1' if host in {'localhost', '127.1'} else '8.8.8.8'
        return [(socket.AF_INET6 if ':' in address else socket.AF_INET, socket.SOCK_STREAM, 6, '', (address, port))]
    original_connect = socket.socket.connect
    def blocked(sock, address, *args, **kwargs):
        import sys
        # Windows implements asyncio's internal socketpair through loopback TCP.
        if sys._getframe(1).f_code.co_name == '_fallback_socketpair':
            return original_connect(sock, address, *args, **kwargs)
        raise AssertionError('Real network access is forbidden in backend tests; mock the provider/transport')
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(socket.socket, 'connect', blocked)
    monkeypatch.setattr(socket.socket, 'connect_ex', blocked)


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
    from backend.app.services.materials import material_service

    data_dir = tmp_path / "data"
    monkeypatch.setattr(database, "DATA_DIR", data_dir)
    monkeypatch.setattr(database, "DB_PATH", data_dir / "qcmaker.sqlite3")
    monkeypatch.setattr(ppt_service, "OUTPUT_DIR", tmp_path / "generated_ppts")
    monkeypatch.setattr(ppt_service, "TEMPLATE_DIR", tmp_path / "templates")
    monkeypatch.setattr(rag_service, "persist_directory", str(tmp_path / "chroma_db"))
    monkeypatch.setattr(rag_service, "vector_store", None)
    monkeypatch.setattr(rag_service, "collection_key", "")
    monkeypatch.setattr(rag_service, "config_revision", -1)
    monkeypatch.setattr(material_service, "storage_root", tmp_path / "materials")
    return tmp_path


@pytest.fixture()
def client(tmp_path, isolated_settings, isolated_storage):
    from backend.main import app

    with TestClient(app) as test_client:
        yield test_client
