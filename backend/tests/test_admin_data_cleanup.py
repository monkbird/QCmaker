import json
from datetime import UTC, datetime, timedelta


def test_dataset_cleanup_does_not_delete_expired_dataset_referenced_by_live_session(isolated_storage):
    from backend.app.repositories.database import connect, init_database, transaction
    from backend.app.services.admin_cleanup import run_cleanup

    now = datetime.now(UTC)
    init_database()
    with transaction(immediate=True) as db:
        db.execute(
            "INSERT INTO datasets VALUES(?,?,?,?,?,?,?,?,?,?)",
            ("ds_live", "data.csv", 0, None, "[]", "[]", "[]", json.dumps({"mode": "detected", "issues": [], "applied_rules": []}), (now - timedelta(days=2)).isoformat(), (now - timedelta(hours=1)).isoformat()),
        )
        state = json.dumps({"dataset_id": "ds_live", "project_id": "p1", "topic": "topic"})
        db.execute("INSERT INTO discussion_sessions VALUES(?,?,?,?,?,?,?,?)", ("s1", "round_done", state, 1, None, 0, None, (now + timedelta(hours=1)).isoformat()))

    result = run_cleanup(scopes=["datasets"], dry_run=False, now=now)
    db = connect()
    try:
        exists = db.execute("SELECT 1 FROM datasets WHERE dataset_id='ds_live'").fetchone()
    finally:
        db.close()

    assert exists is not None
    assert result["scopes"]["datasets"]["skipped"] == 1


def test_cleanup_releases_stale_reserved_but_retains_unknown_holds(isolated_storage):
    from backend.app.repositories.database import connect, init_database, transaction
    from backend.app.services.admin_cleanup import run_cleanup

    old = (datetime.now(UTC) - timedelta(hours=2)).isoformat()
    init_database()
    with transaction(immediate=True) as db:
        db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,?)", ("r_reserved", "rq1", "openai", "m", "0.20", "reserved", old))
        db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,?)", ("r_unknown", "rq2", "openai", "m", "0.30", "usage_unknown", old))
    result = run_cleanup(scopes=["reservations"], dry_run=False)

    db = connect()
    try:
        states = {row[0]: row[1] for row in db.execute("SELECT id,status FROM reservations").fetchall()}
    finally:
        db.close()
    assert states == {"r_reserved": "released", "r_unknown": "usage_unknown"}
    assert result["scopes"]["reservations"]["succeeded"] == 1
    assert result["retained_unknown_count"] == 1
