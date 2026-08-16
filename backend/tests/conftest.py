
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    from backend.app.repositories import database
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "qcmaker.sqlite3")
    from backend.main import app
    with TestClient(app) as test_client:
        yield test_client

