import json
from datetime import UTC, datetime
from uuid import uuid4

from backend.app.core.errors import AppException
from backend.app.models.evidence import ArtifactSnapshot, ChapterSnapshot
from backend.app.repositories.database import connect, transaction


def chapter_snapshot(project_id: str, chapter_id: str, revision: int) -> ChapterSnapshot:
    db = connect()
    try:
        row = db.execute('SELECT snapshot_json FROM chapters WHERE project_id=? AND chapter_id=? AND revision=?', (project_id, chapter_id, revision)).fetchone()
    finally:
        db.close()
    if row is None:
        raise AppException('CHAPTER_NOT_FOUND', '章节版本不存在', 404)
    snapshot = ChapterSnapshot.model_validate_json(row['snapshot_json'])
    if (snapshot.project_id, snapshot.chapter_id, snapshot.revision) != (project_id, chapter_id, revision):
        raise AppException('CHAPTER_CORRUPT', '章节版本记录不一致', 409)
    return snapshot


def _decode(row) -> ArtifactSnapshot:
    return ArtifactSnapshot(artifact_id=row['artifact_id'], project_id=row['project_id'], content_version=row['content_version'],
        upstream_versions=json.loads(row['upstream_versions_json']), generated_at=row['generated_at'], artifact_kind=row['artifact_kind'],
        operation_id=row['operation_id'], payload=json.loads(row['payload_json']), stale=bool(row['stale']), stale_reasons=json.loads(row['stale_reasons_json']))


def list_artifacts(project_id: str) -> list[ArtifactSnapshot]:
    refresh_stale(project_id)
    db = connect()
    try:
        return [_decode(row) for row in db.execute('SELECT * FROM artifacts WHERE project_id=? ORDER BY generated_at DESC', (project_id,))]
    finally:
        db.close()


def get_artifact(project_id: str, artifact_id: str) -> ArtifactSnapshot:
    refresh_stale(project_id)
    db = connect()
    try:
        row = db.execute('SELECT * FROM artifacts WHERE project_id=? AND artifact_id=?', (project_id, artifact_id)).fetchone()
    finally:
        db.close()
    if row is None:
        raise AppException('ARTIFACT_NOT_FOUND', '成果不存在', 404)
    return _decode(row)


def by_operation(project_id: str, operation_id: str, request_hash: str) -> ArtifactSnapshot | None:
    db = connect()
    try:
        row = db.execute('SELECT * FROM artifacts WHERE project_id=? AND operation_id=?', (project_id, operation_id)).fetchone()
    finally:
        db.close()
    if row is None:
        return None
    artifact = _decode(row)
    if artifact.payload.get('request_hash') != request_hash:
        raise AppException('OPERATION_CONFLICT', '操作编号已用于不同输入，请重新生成', 409)
    return artifact


def save(project_id: str, kind: str, operation_id: str, upstream: dict[str, int], payload: dict, db=None) -> ArtifactSnapshot:
    artifact = ArtifactSnapshot(artifact_id=str(uuid4()), project_id=project_id, artifact_kind=kind, operation_id=operation_id,
        content_version=1, upstream_versions=upstream, generated_at=datetime.now(UTC), payload=payload)

    def insert(conn):
        conn.execute('INSERT INTO artifacts(artifact_id,project_id,artifact_kind,content_version,upstream_versions_json,generated_at,stale,stale_reasons_json,payload_json,operation_id) VALUES(?,?,?,?,?,?,?,?,?,?)',
            (artifact.artifact_id, project_id, kind, 1, json.dumps(upstream), artifact.generated_at.isoformat(), 0, '[]', json.dumps(payload, ensure_ascii=False), operation_id))

    if db is not None:
        insert(db)
    else:
        with transaction(immediate=True) as conn:
            insert(conn)
    return artifact


def refresh_stale(project_id: str) -> None:
    """Reconciliation after restart also covers events delivered while offline."""
    with transaction(immediate=True) as db:
        # Iterate to a fixpoint: an export may be listed before its chart, so a
        # single pass can otherwise miss transitive stale propagation.
        changed = True
        while changed:
            changed = False
            for row in db.execute('SELECT * FROM artifacts WHERE project_id=? ORDER BY artifact_id', (project_id,)).fetchall():
                reasons = set(json.loads(row['stale_reasons_json']))
                for key, version in json.loads(row['upstream_versions_json']).items():
                    if key.startswith('chapter:'):
                        current = db.execute('SELECT MAX(revision) FROM chapters WHERE project_id=? AND chapter_id=?', (project_id, key[8:])).fetchone()[0]
                        if current != version: reasons.add(f'{key}已变化（输入版本{version}）')
                    elif key.startswith('material:'):
                        current = db.execute('SELECT current_version FROM materials WHERE project_id=? AND material_id=?', (project_id, key[9:])).fetchone()
                        if not current or current[0] != version: reasons.add(f'{key}已变化（输入版本{version}）')
                    elif key.startswith('chart:'):
                        current = db.execute('SELECT stale,content_version FROM artifacts WHERE project_id=? AND artifact_id=?', (project_id, key[6:])).fetchone()
                        if not current or current[0] or current[1] != version: reasons.add(f'{key}需复核')
                if reasons and (not row['stale'] or sorted(reasons) != json.loads(row['stale_reasons_json'])):
                    db.execute('UPDATE artifacts SET stale=1,stale_reasons_json=? WHERE artifact_id=?', (json.dumps(sorted(reasons), ensure_ascii=False), row['artifact_id']))
                    changed = True
