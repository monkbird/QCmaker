"""Offline, checksummed snapshot. Restore only into a new staging directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

ARTIFACTS = ('.env', 'backend/data/chroma_db', 'backend/generated_ppts', 'backend/data/admin_csrf.key')
DATABASE = 'backend/data/qcmaker.sqlite3'


def digest(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def snapshot(root: Path, destination: Path) -> None:
    root, destination = root.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError('快照目标必须是尚不存在的目录')
    if destination == root or root in destination.parents:
        raise ValueError('快照必须位于项目目录外')
    destination.mkdir(parents=True)
    database = root / DATABASE
    if database.exists():
        target = destination / DATABASE
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True) as source_db:
            with sqlite3.connect(target) as target_db:
                source_db.backup(target_db)
                if target_db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('数据库完整性检查失败')
    for relative in ARTIFACTS:
        source = root / relative
        if not source.exists():
            continue
        if source.is_symlink():
            raise ValueError('快照不接受符号链接')
        files = source.rglob('*') if source.is_dir() else [source]
        for item in files:
            if item.is_symlink():
                raise ValueError('快照不接受符号链接')
            if item.is_file():
                target = destination / item.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(item, target)
    files = {str(path.relative_to(destination)).replace('\\', '/'): digest(path)
             for path in destination.rglob('*') if path.is_file()}
    (destination / 'manifest.json').write_text(json.dumps({
        'format': 1, 'created_at': datetime.now(UTC).isoformat(), 'files': files,
        'requires_stopped_service': True,
    }, indent=2), encoding='utf-8')


def restore(snapshot_dir: Path, destination: Path) -> None:
    snapshot_dir, destination = snapshot_dir.resolve(), destination.resolve()
    if destination.exists():
        raise ValueError('恢复目标必须是新的暂存目录，禁止覆盖在线数据')
    manifest = json.loads((snapshot_dir / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('format') != 1:
        raise ValueError('快照格式不受支持')
    verified = []
    for relative, expected in manifest['files'].items():
        source = (snapshot_dir / relative).resolve()
        target = (destination / relative).resolve()
        if snapshot_dir not in source.parents or destination not in target.parents or source.is_symlink():
            raise ValueError('快照包含非法路径')
        if not source.is_file() or digest(source) != expected:
            raise ValueError('快照校验失败，未执行恢复')
        verified.append((source, target))
    destination.mkdir(parents=True)
    for source, target in verified:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
    database = destination / DATABASE
    if database.exists():
        with sqlite3.connect(database) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('恢复数据库完整性检查失败')
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE name='admin_sessions'").fetchone()
            if exists:
                # Never re-enable an old authenticated browser session on restore.
                db.execute('DELETE FROM admin_sessions')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['backup', 'restore'])
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--service-stopped', action='store_true', help='确认 API、清理和恢复 worker 均已停止，Chroma 已关闭')
    args = parser.parse_args()
    if not args.service_stopped:
        parser.error('请先停止服务和全部 worker，再传 --service-stopped')
    (snapshot if args.action == 'backup' else restore)(args.source, args.destination)
    print('完成；快照含配置密钥，请按服务账号权限保管。恢复数据位于新目录，尚未替换在线数据。')


if __name__ == '__main__':
    main()
