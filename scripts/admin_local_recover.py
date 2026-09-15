"""Controlled local administrator recovery.

This is intentionally a command-line/local-host workflow.  There is no HTTP
reset endpoint.  The operation changes the DB-authoritative credential,
revokes all sessions, and leaves an ``ADMIN_LOCAL_RECOVERY`` audit record in
the same transaction.  Enabling the admin surface updates the local .env file;
the process must be restarted for a running service to observe it.
"""

from __future__ import annotations

import argparse
import getpass
import os
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.core import config as core_config  # noqa: E402
from backend.app.core.admin_security import hash_password, normalize_username  # noqa: E402
from backend.app.repositories import database  # noqa: E402
from backend.app.services.audit import record_audit_tx  # noqa: E402


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _assert_local_write_access() -> None:
    # The script has no network listener.  Requiring a writable local DB
    # parent catches accidental invocation against a read-only/mounted
    # production snapshot before the credential transaction begins.
    parent = Path(database.DB_PATH).resolve().parent
    if not parent.exists():
        parent.mkdir(parents=True, exist_ok=True)
    if not os.access(parent, os.W_OK):
        raise PermissionError("数据库目录不可写，无法执行本机恢复")


def _set_env_enabled(enabled: bool) -> None:
    path = Path(core_config.ENV_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    values: dict[str, str] = {}
    if path.exists():
        from dotenv import dotenv_values

        values = {str(key): str(value) for key, value in dotenv_values(path).items() if value is not None}
    values["ADMIN_ENABLED"] = "true" if enabled else "false"
    descriptor, temp_name = tempfile.mkstemp(prefix=".env.recovery.", dir=path.parent, text=True)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            for key in sorted(values):
                value = values[key].replace("\\", "\\\\").replace("'", "\\'").replace("\r", "").replace("\n", "")
                stream.write(f"{key}='{value}'\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def recover_admin(
    password: str,
    *,
    username: str | None = None,
    enable: bool = True,
    reason: str = "local administrator recovery",
    request_id: str | None = None,
) -> dict[str, object]:
    """Recover the DB-authoritative admin credential from the local host."""

    _assert_local_write_access()
    new_hash = hash_password(password)
    selected_username = normalize_username(username) if username else None
    database.init_database()
    now = _iso_now()
    request_id = request_id or f"local_{uuid4().hex}"
    with database.transaction(immediate=True) as db:
        row = db.execute("SELECT * FROM admin_users ORDER BY created_at,user_id LIMIT 1").fetchone()
        if selected_username and row and row["username"] != selected_username:
            # Local recovery is the one explicitly permitted path for an
            # operator to change a forgotten username.
            duplicate = db.execute("SELECT user_id FROM admin_users WHERE username=?", (selected_username,)).fetchone()
            if duplicate and duplicate["user_id"] != row["user_id"]:
                raise ValueError("指定的管理员用户名已存在")
        if row is None:
            if not selected_username:
                selected_username = "admin"
            user_id = f"admin_{uuid4().hex}"
            db.execute(
                "INSERT INTO admin_users(user_id,username,password_hash,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (user_id, selected_username, new_hash, 1, now, now),
            )
        else:
            user_id = row["user_id"]
            selected_username = selected_username or row["username"]
            db.execute(
                "UPDATE admin_users SET username=?,password_hash=?,is_active=1,updated_at=? WHERE user_id=?",
                (selected_username, new_hash, now, user_id),
            )
        revoked = db.execute("UPDATE admin_sessions SET revoked_at=? WHERE revoked_at IS NULL", (now,)).rowcount
        record_audit_tx(
            db,
            action="ADMIN_LOCAL_RECOVERY",
            actor_id=None,
            actor_name="local-recovery",
            request_id=request_id,
            result="SUCCEEDED",
            reason=reason,
            target_type="admin_user",
            target_id=user_id,
            detail={"revoked_sessions": revoked, "enabled_requested": enable},
        )
    if enable:
        _set_env_enabled(True)
    return {"user_id": user_id, "username": selected_username, "revoked_sessions": int(revoked), "enabled": enable, "request_id": request_id}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本机恢复 QCmaker 管理员账号")
    parser.add_argument("--username", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--no-enable", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    first = getpass.getpass("新管理员密码（至少12个字符，输入不回显）：")
    second = getpass.getpass("再次输入新管理员密码（输入不回显）：")
    if first != second:
        parser.error("两次密码输入不一致")
    try:
        result = recover_admin(first, username=args.username, enable=not args.no_enable)
    except (OSError, PermissionError, ValueError) as exc:
        parser.error(str(exc))
    print(f"已完成本机恢复：用户 {result['username']}，吊销会话 {result['revoked_sessions']} 个。请重启服务后重新登录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
