import sqlite3
import pytest

from backend.app.repositories import database


def test_v2_migration_preserves_v1_checksum_and_creates_qc_tables(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "qc.sqlite3")
    monkeypatch.setattr(database, "DATA_DIR", tmp_path)
    database.init_database()
    with database.connect() as db:
        versions = {r[0]: r[2] for r in db.execute("SELECT version, applied_at, checksum FROM schema_versions")}
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert versions[1] == database._SCHEMA_CHECKSUM
    assert versions[2] == database._QC_SCHEMA_CHECKSUM
    assert {"config_profiles", "materials", "material_versions", "material_parse_units", "material_cleaning_previews", "material_events", "material_upload_operations", "material_event_consumers", "dataset_versions", "dataset_material_links", "project_contexts", "chapters", "chapter_reviews", "source_dependencies", "project_activity", "artifacts"} <= names


def test_v2_migration_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "qc.sqlite3")
    monkeypatch.setattr(database, "DATA_DIR", tmp_path)
    database.init_database()
    database.init_database()
    with database.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM schema_versions").fetchone()[0] == 2


def test_real_v1_upgrade_failure_rolls_back_and_can_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(database, 'DB_PATH', tmp_path / 'old.sqlite3')
    monkeypatch.setattr(database, 'DATA_DIR', tmp_path)
    with database.transaction(immediate=True) as db:
        for statement in (*database._BUSINESS_SCHEMA, *database._ADMIN_SCHEMA, *database._ADMIN_INDEXES):
            db.execute(statement)
        db.execute('CREATE TABLE schema_versions(version INTEGER PRIMARY KEY, applied_at TEXT, checksum TEXT)')
        db.execute('INSERT INTO schema_versions VALUES(1,?,?)', ('2026-01-01', database._SCHEMA_CHECKSUM))
        db.execute("INSERT INTO datasets VALUES('old','old.csv',0,NULL,'[]','[]','[]','{}','2026-01-01','2099-01-01')")
    original = database.QC_MIGRATION_V2
    monkeypatch.setattr(database, 'QC_MIGRATION_V2', (*original[:3], 'INVALID MIGRATION SQL'))
    with pytest.raises(sqlite3.OperationalError):
        database.init_database()
    with database.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM schema_versions').fetchone()[0] == 1
        assert db.execute("SELECT name FROM sqlite_master WHERE name='config_profiles'").fetchone() is None
        assert db.execute('SELECT filename FROM datasets').fetchone()[0] == 'old.csv'
    monkeypatch.setattr(database, 'QC_MIGRATION_V2', original)
    database.init_database()
    database.init_database()
    with database.connect() as db:
        assert db.execute('SELECT COUNT(*) FROM schema_versions').fetchone()[0] == 2
        assert db.execute('SELECT filename FROM datasets').fetchone()[0] == 'old.csv'
