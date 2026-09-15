import sqlite3

import pytest

from scripts.admin_snapshot import DATABASE, restore, snapshot


def test_snapshot_restores_same_batch_and_revokes_old_sessions(tmp_path):
    root = tmp_path / 'app'
    path = root / DATABASE
    path.parent.mkdir(parents=True)
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE admin_sessions(id TEXT)')
        db.execute("INSERT INTO admin_sessions VALUES('old')")
        db.execute('CREATE TABLE business(value TEXT)')
        db.execute("INSERT INTO business VALUES('kept')")
    (root / '.env').write_text('SECRET=test', encoding='utf-8')
    archive, restored = tmp_path / 'archive', tmp_path / 'restored'
    snapshot(root, archive)
    restore(archive, restored)
    with sqlite3.connect(restored / DATABASE) as db:
        assert db.execute('SELECT COUNT(*) FROM admin_sessions').fetchone()[0] == 0
        assert db.execute('SELECT value FROM business').fetchone()[0] == 'kept'
    assert (restored / '.env').read_text() == 'SECRET=test'


def test_corrupt_snapshot_does_not_create_restore_target(tmp_path):
    root = tmp_path / 'app'
    root.mkdir()
    (root / '.env').write_text('original')
    archive, restored = tmp_path / 'archive', tmp_path / 'restore'
    snapshot(root, archive)
    (archive / '.env').write_text('tampered')
    with pytest.raises(ValueError, match='校验'):
        restore(archive, restored)
    assert not restored.exists()
