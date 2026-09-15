"""Independent administrator authentication and session security.

The business API continues to use ``core.security.verify_access_token``.  This
module owns the separate admin identity, cookie session, CSRF, bootstrap, and
durable login throttling policy described by the admin-console plan.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import dotenv_values
from fastapi import Request

from backend.app.core.errors import AppException
from backend.app.repositories import database
from backend.app.services.audit import hash_user_agent, record_audit_tx

PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 600_000
PASSWORD_SALT_BYTES = 16
PASSWORD_DK_BYTES = 32
SESSION_COOKIE_NAME = "qc_admin_sid"
SESSION_COOKIE_PATH = "/api/admin"
CSRF_HEADER_NAME = "x-csrf-token"
USER_ACTIVITY_HEADER_NAME = "x-admin-user-activity"
CSRF_KEY_BYTES = 32
_CSRF_PURPOSE = b"qcmaker-admin-csrf-v1"
_CSRF_KEY_LOCK = threading.RLock()
_CSRF_KEY_CACHE: dict[str, bytes] = {}
_PASSWORD_SEMAPHORE = threading.BoundedSemaphore(4)
_PASSWORD_WAIT_SECONDS = 2.0


class AdminSecurityError(AppException):
    """Stable error type for admin callers and tests."""


class AdminRateLimitError(AdminSecurityError):
    def __init__(self, code: str, message: str, retry_after: int, details: dict[str, Any] | None = None):
        self.retry_after = max(1, int(retry_after))
        super().__init__(code, message, 429, details)


@dataclass(frozen=True)
class AdminSettings:
    enabled: bool
    bootstrap_username: str | None
    bootstrap_password_hash: str | None
    session_idle_minutes: int
    session_absolute_hours: int
    login_rate_per_minute: int
    allowed_ips: tuple[ipaddress._BaseNetwork, ...]
    csrf_token_ttl_minutes: int
    max_sessions: int
    trusted_proxy: bool
    forwarded_for_position: int
    environment: str
    csrf_key_file: Path | None


@dataclass(frozen=True)
class AdminInitResult:
    enabled: bool
    initialized: bool
    created: bool = False
    user_id: str | None = None
    username: str | None = None


@dataclass(frozen=True)
class AdminPrincipal:
    """Authenticated admin context.

    ``session_secret`` is the raw cookie value and must never be serialized or
    included in an API response.  It is retained only for server-side CSRF
    derivation during the current request.
    """

    user_id: str
    username: str
    session_id: str
    session_secret: str
    csrf_token: str
    csrf_generation: int
    csrf_token_created_at: datetime
    created_at: datetime
    last_activity_at: datetime
    last_request_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime
    ip: str | None = None
    user_agent_hash: str | None = None
    is_active: bool = True
    reauthenticated_at: datetime | None = None


@dataclass(frozen=True)
class PasswordChangeResult:
    relogin_required: bool = True


def _env_values() -> dict[str, str]:
    """Read admin values with process environment taking precedence over .env."""

    try:
        from backend.app.core import config as core_config

        env_path = core_config.ENV_PATH
        core_settings = core_config.get_settings()
    except Exception:
        env_path = None
        core_settings = None
    values: dict[str, str] = {}
    if env_path and Path(env_path).exists():
        values.update({str(key): str(value) for key, value in dotenv_values(env_path).items() if value is not None})
    for key in (
        "ADMIN_ENABLED",
        "ADMIN_BOOTSTRAP_USERNAME",
        "ADMIN_BOOTSTRAP_PASSWORD_HASH",
        "ADMIN_SESSION_IDLE_MINUTES",
        "ADMIN_SESSION_ABSOLUTE_HOURS",
        "ADMIN_LOGIN_RATE_PER_MINUTE",
        "ADMIN_ALLOWED_IPS",
        "ADMIN_CSRF_TOKEN_TTL_MINUTES",
        "ADMIN_MAX_SESSIONS",
        "ADMIN_TRUSTED_PROXY",
        "ADMIN_FORWARDED_FOR_POSITION",
        "ADMIN_ALLOWED_ORIGINS",
        "ADMIN_CSRF_KEY_FILE",
        "ENVIRONMENT",
        "APP_ENV",
        "DEBUG",
    ):
        if key in os.environ:
            values[key] = os.environ[key]
        elif core_settings is not None and hasattr(core_settings, key):
            raw = getattr(core_settings, key)
            if raw is not None:
                values[key] = str(raw)
    return values


def _bool(raw: str | None, default: bool = False) -> bool:
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off", ""}:
        return False
    raise ValueError(f"invalid boolean value: {raw}")


def _positive_int(raw: str | None, default: int, *, minimum: int = 1, maximum: int = 10_000_000) -> int:
    try:
        value = default if raw is None or raw == "" else int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer value: {raw}") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"integer value outside allowed range: {value}")
    return value


def normalize_username(username: str) -> str:
    if not isinstance(username, str):
        raise ValueError("username must be a string")
    username = username.strip()
    if not username or len(username) > 128 or any(ord(char) < 32 or ord(char) == 127 for char in username):
        raise ValueError("username format is invalid")
    return username.casefold()


def get_admin_settings() -> AdminSettings:
    values = _env_values()
    allowed: list[ipaddress._BaseNetwork] = []
    for raw in (values.get("ADMIN_ALLOWED_IPS") or "").split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            allowed.append(ipaddress.ip_network(item, strict=False))
        except ValueError as exc:
            raise ValueError(f"ADMIN_ALLOWED_IPS contains an invalid network: {item}") from exc
    environment = (values.get("ENVIRONMENT") or values.get("APP_ENV") or ("development" if _bool(values.get("DEBUG"), False) else "production")).strip().lower()
    key_path = values.get("ADMIN_CSRF_KEY_FILE")
    if key_path:
        configured_key_path = Path(key_path).expanduser()
        if not configured_key_path.is_absolute():
            configured_key_path = database.DATA_DIR / configured_key_path
    else:
        configured_key_path = None
    return AdminSettings(
        enabled=_bool(values.get("ADMIN_ENABLED"), False),
        bootstrap_username=(values.get("ADMIN_BOOTSTRAP_USERNAME") or "").strip() or None,
        bootstrap_password_hash=(values.get("ADMIN_BOOTSTRAP_PASSWORD_HASH") or "").strip() or None,
        session_idle_minutes=_positive_int(values.get("ADMIN_SESSION_IDLE_MINUTES"), 30, maximum=24 * 60),
        session_absolute_hours=_positive_int(values.get("ADMIN_SESSION_ABSOLUTE_HOURS"), 8, maximum=24 * 30),
        login_rate_per_minute=_positive_int(values.get("ADMIN_LOGIN_RATE_PER_MINUTE"), 5, maximum=10_000),
        allowed_ips=tuple(allowed),
        csrf_token_ttl_minutes=_positive_int(values.get("ADMIN_CSRF_TOKEN_TTL_MINUTES"), 120, maximum=24 * 60),
        max_sessions=_positive_int(values.get("ADMIN_MAX_SESSIONS"), 20, maximum=10_000),
        trusted_proxy=_bool(values.get("ADMIN_TRUSTED_PROXY"), False),
        forwarded_for_position=_positive_int(values.get("ADMIN_FORWARDED_FOR_POSITION"), 0, minimum=0, maximum=20),
        environment=environment,
        csrf_key_file=configured_key_path,
    )


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat()


def _dt(value: str | datetime) -> datetime:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _schema_available() -> None:
    try:
        with database.connect() as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except Exception as exc:
        raise AdminSecurityError("ADMIN_SCHEMA_UNAVAILABLE", "管理数据库不可用", 503) from exc
    required = {
        "schema_versions",
        "admin_users",
        "admin_sessions",
        "admin_login_throttles",
        "audit_logs",
        "operation_events",
        "admin_operations",
        "admin_operation_attempts",
        "admin_security_meta",
    }
    if not required <= tables:
        raise AdminSecurityError("ADMIN_SCHEMA_UNAVAILABLE", "管理数据库未完成迁移", 503)


def _ensure_schema() -> None:
    try:
        _schema_available()
    except AdminSecurityError as exc:
        if exc.code != "ADMIN_SCHEMA_UNAVAILABLE":
            raise
        try:
            from backend.app.repositories.database import init_database

            init_database()
            _schema_available()
        except Exception as migration_exc:
            raise AdminSecurityError("ADMIN_SCHEMA_UNAVAILABLE", "管理数据库未完成迁移", 503) from migration_exc


def hash_password(password: str, *, iterations: int = PASSWORD_ITERATIONS) -> str:
    if not isinstance(password, str) or len(password) < 12:
        raise ValueError("管理员密码至少需要 12 个字符")
    if len(password) > 512:
        raise ValueError("管理员密码过长")
    if iterations < PASSWORD_ITERATIONS:
        raise ValueError("PBKDF2 迭代次数低于安全下限")
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=PASSWORD_DK_BYTES)
    return "$".join(
        (
            PASSWORD_ALGORITHM,
            str(iterations),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        )
    )


def _parse_password_hash(encoded: str) -> tuple[int, bytes, bytes]:
    if not isinstance(encoded, str):
        raise ValueError("password hash must be text")
    parts = encoded.split("$")
    if len(parts) != 4 or parts[0] != PASSWORD_ALGORITHM:
        raise ValueError("unsupported password hash algorithm")
    try:
        iterations = int(parts[1])
        salt = base64.b64decode(parts[2], validate=True)
        expected = base64.b64decode(parts[3], validate=True)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid password hash encoding") from exc
    if iterations < PASSWORD_ITERATIONS or iterations > 10_000_000 or len(salt) < PASSWORD_SALT_BYTES or len(expected) != PASSWORD_DK_BYTES:
        raise ValueError("password hash parameters are outside the security policy")
    return iterations, salt, expected


def verify_password(password: str, encoded: str) -> bool:
    try:
        iterations, salt, expected = _parse_password_hash(encoded)
    except ValueError:
        return False
    if not isinstance(password, str) or len(password) > 512:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=len(expected))
    return hmac.compare_digest(actual, expected)


def _verify_password_guarded(password: str, encoded: str) -> bool:
    if not _PASSWORD_SEMAPHORE.acquire(timeout=_PASSWORD_WAIT_SECONDS):
        raise AdminRateLimitError("ADMIN_PASSWORD_BUSY", "当前登录请求较多，请稍后再试", 2)
    try:
        return verify_password(password, encoded)
    finally:
        _PASSWORD_SEMAPHORE.release()


def _hash_password_guarded(password: str) -> str:
    if not _PASSWORD_SEMAPHORE.acquire(timeout=_PASSWORD_WAIT_SECONDS):
        raise AdminRateLimitError("ADMIN_PASSWORD_BUSY", "当前登录请求较多，请稍后再试", 2)
    try:
        return hash_password(password)
    finally:
        _PASSWORD_SEMAPHORE.release()


_DUMMY_HASH: str | None = None
_DUMMY_HASH_LOCK = threading.Lock()


def _dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        with _DUMMY_HASH_LOCK:
            if _DUMMY_HASH is None:
                # This is generated once per process and never stored or
                # returned; unknown usernames take the same PBKDF2 path.
                _DUMMY_HASH = hash_password("qcmaker-dummy-password")
    return _DUMMY_HASH


def _csrf_key_path(settings: AdminSettings | None = None) -> Path:
    configured = settings.csrf_key_file if settings else get_admin_settings().csrf_key_file
    return configured or (database.DATA_DIR / "admin_csrf.key")


def _write_private_key(path: Path, key: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(key)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _load_csrf_key(settings: AdminSettings | None = None) -> bytes:
    path = _csrf_key_path(settings)
    cache_key = str(path.resolve())
    with _CSRF_KEY_LOCK:
        cached = _CSRF_KEY_CACHE.get(cache_key)
        if cached is not None and path.exists():
            return cached
        was_missing = False
        try:
            key = path.read_bytes()
        except FileNotFoundError:
            key = secrets.token_bytes(CSRF_KEY_BYTES)
            _write_private_key(path, key)
            was_missing = True
        except OSError as exc:
            raise AdminSecurityError("ADMIN_CSRF_KEY_UNAVAILABLE", "管理安全密钥不可用", 503) from exc
        if len(key) != CSRF_KEY_BYTES:
            raise AdminSecurityError("ADMIN_CSRF_KEY_INVALID", "管理安全密钥格式无效", 503)
        _CSRF_KEY_CACHE[cache_key] = key
        if was_missing:
            # Losing the signing key must invalidate every cookie that could
            # otherwise be presented with an unverifiable CSRF token.
            try:
                with database.transaction(immediate=True) as db:
                    version = _current_csrf_key_version(db) + 1
                    db.execute("UPDATE admin_sessions SET revoked_at=?,csrf_key_version=? WHERE revoked_at IS NULL", (_iso(_now()), version))
                    db.execute("INSERT INTO admin_security_meta(meta_key,meta_value) VALUES('csrf_key_version',?) ON CONFLICT(meta_key) DO UPDATE SET meta_value=excluded.meta_value", (str(version),))
            except Exception as exc:
                raise AdminSecurityError("ADMIN_CSRF_KEY_UNAVAILABLE", "管理安全密钥轮换失败", 503) from exc
        return key


def _current_csrf_key_version(db=None) -> int:
    owns = db is None
    if owns:
        connection = database.connect()
    else:
        connection = db
    try:
        row = connection.execute("SELECT meta_value FROM admin_security_meta WHERE meta_key='csrf_key_version'").fetchone()
        session_row = connection.execute("SELECT COALESCE(MAX(csrf_key_version),1) FROM admin_sessions").fetchone()
        marker = int(row[0]) if row else 1
        session_version = int(session_row[0]) if session_row else 1
        return max(1, marker, session_version)
    finally:
        if owns:
            connection.close()


def rotate_csrf_key(*, reason: str = "key_rotation", request_id: str | None = None) -> int:
    """Generate a new key and revoke all sessions before returning its version."""

    settings = get_admin_settings()
    path = _csrf_key_path(settings)
    new_key = secrets.token_bytes(CSRF_KEY_BYTES)
    with _CSRF_KEY_LOCK:
        _write_private_key(path, new_key)
        cache_key = str(path.resolve())
        _CSRF_KEY_CACHE[cache_key] = new_key
    now = _iso(_now())
    with database.transaction(immediate=True) as db:
        version = _current_csrf_key_version(db) + 1
        db.execute("UPDATE admin_sessions SET revoked_at=?,csrf_key_version=? WHERE revoked_at IS NULL", (now, version))
        db.execute("INSERT INTO admin_security_meta(meta_key,meta_value) VALUES('csrf_key_version',?) ON CONFLICT(meta_key) DO UPDATE SET meta_value=excluded.meta_value", (str(version),))
        # Keep a durable marker even when no session existed to infer the
        # version from.  A zero-row session is fine; the key version is stored
        # with the next login as the maximum seen version.
        if request_id:
            record_audit_tx(
                db,
                action="SESSION_REVOKE_ALL",
                actor_id=None,
                actor_name="system",
                request_id=request_id,
                result="SUCCEEDED",
                reason=reason,
                detail={"csrf_key_version": version},
            )
    return version


def _derive_csrf_token(*, key: bytes, session_id: str, session_secret: str, generation: int, created_at: str, key_version: int) -> str:
    payload = b"|".join(
        (
            _CSRF_PURPOSE,
            session_id.encode("utf-8"),
            str(generation).encode("ascii"),
            str(key_version).encode("ascii"),
            created_at.encode("utf-8"),
            session_secret.encode("utf-8"),
        )
    )
    digest = hmac.new(key, payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _parse_source_ip(source_ip: str | None) -> str:
    raw = (source_ip or "unknown").strip()
    if not raw:
        return "unknown"
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return raw[:128]


def client_ip(request: Request, settings: AdminSettings | None = None) -> str:
    settings = settings or get_admin_settings()
    peer = request.client.host if request.client else "unknown"
    if not settings.trusted_proxy:
        return _parse_source_ip(peer)
    forwarded = request.headers.get("x-forwarded-for", "")
    values = [item.strip() for item in forwarded.split(",") if item.strip()]
    position = settings.forwarded_for_position
    candidate = values[position] if position < len(values) else peer
    return _parse_source_ip(candidate)


def _ip_allowed(source_ip: str, settings: AdminSettings) -> bool:
    if not settings.allowed_ips:
        return True
    try:
        address = ipaddress.ip_address(source_ip)
    except ValueError:
        return False
    return any(address in network for network in settings.allowed_ips)


def _require_enabled_and_initialized() -> AdminSettings:
    try:
        settings = get_admin_settings()
    except ValueError as exc:
        raise AdminSecurityError("ADMIN_CONFIG_INVALID", "管理安全配置无效", 503) from exc
    if not settings.enabled:
        raise AdminSecurityError("ADMIN_DISABLED", "管理后台已关闭", 503)
    init_admin(settings=settings)
    return settings


def ensure_admin_ready() -> AdminSettings:
    """Validate the independent admin switch, schema, and bootstrap state.

    Login is a pre-session endpoint, so it cannot use ``require_admin`` to
    perform this check. Exposing this small wrapper keeps its failure priority
    identical to protected admin routes: disabled or uninitialized surfaces
    return 503 before request-shape or credential details are considered.
    """

    return _require_enabled_and_initialized()


def init_admin(*, settings: AdminSettings | None = None) -> AdminInitResult:
    settings = settings or get_admin_settings()
    if not settings.enabled:
        return AdminInitResult(enabled=False, initialized=False)
    _ensure_schema()
    try:
        with database.transaction(immediate=True) as db:
            row = db.execute("SELECT user_id,username,is_active FROM admin_users ORDER BY created_at,user_id LIMIT 1").fetchone()
            if row is not None:
                return AdminInitResult(enabled=True, initialized=True, user_id=row["user_id"], username=row["username"])
            if not settings.bootstrap_username or not settings.bootstrap_password_hash:
                raise AdminSecurityError("ADMIN_NOT_INITIALIZED", "管理员尚未完成初始化", 503)
            try:
                username = normalize_username(settings.bootstrap_username)
            except ValueError as exc:
                raise AdminSecurityError("ADMIN_NOT_INITIALIZED", "管理员初始化配置无效", 503) from exc
            try:
                _parse_password_hash(settings.bootstrap_password_hash)
            except ValueError as exc:
                raise AdminSecurityError("ADMIN_NOT_INITIALIZED", "管理员初始化密码哈希无效", 503) from exc
            now = _iso(_now())
            user_id = f"admin_{uuid4().hex}"
            db.execute(
                "INSERT INTO admin_users(user_id,username,password_hash,is_active,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                (user_id, username, settings.bootstrap_password_hash, 1, now, now),
            )
            return AdminInitResult(enabled=True, initialized=True, created=True, user_id=user_id, username=username)
    except AdminSecurityError:
        raise
    except Exception as exc:
        raise AdminSecurityError("ADMIN_SCHEMA_UNAVAILABLE", "管理员初始化失败，管理功能已关闭", 503) from exc


def _extract_cookie(request: Request) -> str | None:
    raw = request.headers.get("cookie", "")
    matches: list[str] = []
    for part in raw.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name.strip() == SESSION_COOKIE_NAME:
            matches.append(value.strip())
    if len(matches) > 1:
        raise AdminSecurityError("ADMIN_SESSION_INVALID", "管理会话无效", 401)
    if matches:
        return matches[0]
    return None


def _session_principal(row: Any, session_secret: str, *, key: bytes | None = None) -> AdminPrincipal:
    key = key or _load_csrf_key()
    created = str(row["csrf_token_created_at"])
    token = _derive_csrf_token(
        key=key,
        session_id=row["session_id"],
        session_secret=session_secret,
        generation=int(row["csrf_generation"]),
        created_at=created,
        key_version=int(row["csrf_key_version"]),
    )
    return AdminPrincipal(
        user_id=row["user_id"],
        username=row["username"],
        session_id=row["session_id"],
        session_secret=session_secret,
        csrf_token=token,
        csrf_generation=int(row["csrf_generation"]),
        csrf_token_created_at=_dt(created),
        created_at=_dt(row["created_at"]),
        last_activity_at=_dt(row["last_activity_at"]),
        last_request_at=_dt(row["last_request_at"]),
        idle_expires_at=_dt(row["idle_expires_at"]),
        absolute_expires_at=_dt(row["absolute_expires_at"]),
        ip=row["ip"],
        user_agent_hash=row["user_agent_hash"],
        is_active=bool(row["is_active"]),
        reauthenticated_at=_dt(row["reauthenticated_at"]) if row["reauthenticated_at"] else None,
    )


def _session_row(db, session_secret: str):
    token_hash = hashlib.sha256(session_secret.encode("utf-8")).hexdigest()
    return db.execute(
        """SELECT s.*,u.username,u.is_active FROM admin_sessions s
           JOIN admin_users u ON u.user_id=s.user_id
           WHERE s.token_hash=?""",
        (token_hash,),
    ).fetchone()


def _expired(row: Any, now: datetime) -> bool:
    return bool(row["revoked_at"]) or now >= _dt(row["absolute_expires_at"]) or now >= _dt(row["idle_expires_at"]) or not bool(row["is_active"])


def validate_session(session_secret: str, *, request: Request | None = None, user_activity: bool | None = None) -> AdminPrincipal:
    if not session_secret or len(session_secret) < 32 or len(session_secret) > 512:
        raise AdminSecurityError("ADMIN_SESSION_INVALID", "管理会话无效", 401)
    settings = _require_enabled_and_initialized()
    now = _now()
    activity = user_activity if user_activity is not None else bool(request and request.headers.get(USER_ACTIVITY_HEADER_NAME) == "1")
    with database.transaction(immediate=True) as db:
        row = _session_row(db, session_secret)
        if row is None:
            raise AdminSecurityError("ADMIN_SESSION_INVALID", "管理会话无效", 401)
        if _expired(row, now):
            if not row["revoked_at"]:
                db.execute("UPDATE admin_sessions SET revoked_at=? WHERE session_id=? AND revoked_at IS NULL", (_iso(now), row["session_id"]))
            raise AdminSecurityError("ADMIN_SESSION_EXPIRED", "管理会话已过期，请重新登录", 401)
        idle_expires_at = _dt(row["idle_expires_at"])
        if activity:
            idle_expires_at = min(now + timedelta(minutes=settings.session_idle_minutes), _dt(row["absolute_expires_at"]))
            db.execute(
                "UPDATE admin_sessions SET last_activity_at=?,last_request_at=?,idle_expires_at=? WHERE session_id=? AND revoked_at IS NULL",
                (_iso(now), _iso(now), _iso(idle_expires_at), row["session_id"]),
            )
        else:
            db.execute("UPDATE admin_sessions SET last_request_at=? WHERE session_id=? AND revoked_at IS NULL", (_iso(now), row["session_id"]))
        updated = db.execute("SELECT s.*,u.username,u.is_active FROM admin_sessions s JOIN admin_users u ON u.user_id=s.user_id WHERE s.session_id=?", (row["session_id"],)).fetchone()
    return _session_principal(updated, session_secret)


def load_session(session_secret: str) -> AdminPrincipal:
    """Compatibility helper for services that only need session validation."""

    return validate_session(session_secret)


def _origin_from_request(request: Request) -> str:
    # Proxy headers are interpreted by the ASGI server's explicitly trusted
    # proxy middleware, if one is configured.  Reading raw forwarded headers
    # here would let a caller choose the origin we consider same-origin.
    return f"{request.url.scheme}://{request.url.netloc}".rstrip("/")


def allowed_origins(request: Request, settings: AdminSettings | None = None) -> set[str]:
    settings = settings or get_admin_settings()
    values = _env_values()
    configured = values.get("ADMIN_ALLOWED_ORIGINS")
    if configured is not None and not configured.strip():
        configured = None
    origins = {item.strip().rstrip("/") for item in (configured or "").split(",") if item.strip()}
    current = _origin_from_request(request)
    # CORS_ORIGINS belongs to the business API and must not silently widen
    # the management surface.  An explicit admin allowlist constrains the
    # computed request origin; it never authorizes another origin by itself.
    if configured is not None:
        return {current} if current in origins else set()
    host = request.url.hostname or ""
    local_host = host in {"localhost", "testserver", "::1"}
    if not local_host:
        try:
            local_host = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local_host = False
    if current in origins or request.url.scheme == "https":
        return {current}
    if settings.environment in {"development", "dev", "test", "testing"} and local_host:
        return {current}
    return set()


def require_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    if not origin:
        raise AdminSecurityError("ADMIN_ORIGIN_REQUIRED", "管理请求缺少同源 Origin", 403)
    try:
        parts = urlsplit(origin)
    except ValueError as exc:
        raise AdminSecurityError("ADMIN_ORIGIN_DENIED", "管理请求来源不受信任", 403) from exc
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.path or parts.query or parts.fragment or parts.username or parts.password:
        raise AdminSecurityError("ADMIN_ORIGIN_DENIED", "管理请求来源不受信任", 403)
    if origin.rstrip("/") not in allowed_origins(request):
        raise AdminSecurityError("ADMIN_ORIGIN_DENIED", "管理请求来源不受信任", 403)


def require_json_content_type(request: Request) -> None:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        raise AdminSecurityError("ADMIN_JSON_REQUIRED", "管理登录必须使用 application/json", 403)


def validate_csrf(request: Request, principal: AdminPrincipal) -> None:
    require_same_origin(request)
    values = request.headers.getlist(CSRF_HEADER_NAME) if hasattr(request.headers, "getlist") else [request.headers.get(CSRF_HEADER_NAME)]
    values = [value for value in values if value is not None]
    if len(values) != 1:
        raise AdminSecurityError("ADMIN_CSRF_INVALID", "管理请求缺少有效 CSRF 令牌", 403)
    settings = get_admin_settings()
    age = _now() - principal.csrf_token_created_at
    if age.total_seconds() >= settings.csrf_token_ttl_minutes * 60:
        raise AdminSecurityError("ADMIN_CSRF_EXPIRED", "CSRF 令牌已过期，请刷新管理页面", 403)
    if not hmac.compare_digest(values[0], principal.csrf_token):
        raise AdminSecurityError("ADMIN_CSRF_INVALID", "管理请求缺少有效 CSRF 令牌", 403)


def require_admin(request: Request) -> AdminPrincipal:
    """FastAPI dependency for every protected admin endpoint."""

    session_secret = _extract_cookie(request)
    if not session_secret:
        # Run the enabled/initialization checks even when no cookie is present
        # so disabled/uninitialized deployments return their explicit 503.
        _require_enabled_and_initialized()
        raise AdminSecurityError("ADMIN_UNAUTHENTICATED", "请先登录管理后台", 401)
    principal = validate_session(session_secret, request=request)
    if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        validate_csrf(request, principal)
    return principal


verify_admin = require_admin
current_admin = require_admin
require_admin_csrf = require_admin


def _throttle_keys(username: str, source_ip: str) -> tuple[str, str]:
    return f"ip:{source_ip}", f"account:{normalize_username(username)}|ip:{source_ip}"


def _throttle_row(db, key: str):
    return db.execute("SELECT * FROM admin_login_throttles WHERE throttle_key=?", (key,)).fetchone()


def _is_lock_active(row: Any, now: datetime) -> bool:
    return bool(row and row["locked_until"] and now < _dt(row["locked_until"]))


def _record_throttle(db, key: str, account_key: str, source_ip: str, now: datetime, *, lock: bool = False) -> int:
    row = _throttle_row(db, key)
    window_started = _dt(row["window_started_at"]) if row else now
    count = int(row["failure_count"]) if row and now - window_started < timedelta(minutes=1) else 0
    count += 1
    locked_until = now + timedelta(minutes=15) if lock else (row["locked_until"] if row else None)
    if row:
        db.execute(
            "UPDATE admin_login_throttles SET account_key=?,source_ip=?,failure_count=?,window_started_at=?,locked_until=?,updated_at=? WHERE throttle_key=?",
            (account_key, source_ip, count, _iso(window_started if count > 1 else now), _iso(locked_until) if isinstance(locked_until, datetime) else locked_until, _iso(now), key),
        )
    else:
        db.execute(
            "INSERT INTO admin_login_throttles(throttle_key,account_key,source_ip,failure_count,window_started_at,locked_until,updated_at) VALUES(?,?,?,?,?,?,?)",
            (key, account_key, source_ip, count, _iso(now), _iso(locked_until) if isinstance(locked_until, datetime) else locked_until, _iso(now)),
        )
    return count


def _clear_throttles(db, keys: tuple[str, str]) -> None:
    db.executemany("DELETE FROM admin_login_throttles WHERE throttle_key=?", ((keys[0],), (keys[1],)))


def _login_failure(
    *,
    username: str,
    source_ip: str,
    request_id: str,
    user_agent: str | None,
    locked: bool = False,
    retry_after: int | None = None,
) -> None:
    now = _now()
    keys = _throttle_keys(username, source_ip)
    try:
        with database.transaction(immediate=True) as db:
            account_key = normalize_username(username)
            account_count = _record_throttle(db, keys[1], account_key, source_ip, now, lock=locked)
            _record_throttle(db, keys[0], account_key, source_ip, now, lock=False)
            record_audit_tx(
                db,
                action="LOGIN_LOCKED" if locked else "LOGIN_FAILURE",
                actor_id=None,
                actor_name="anonymous",
                request_id=request_id,
                result="DENIED",
                error_code="ADMIN_LOGIN_LOCKED" if locked else "ADMIN_LOGIN_FAILED",
                reason="password verification failed",
                detail={"account_key": account_key, "failure_count": account_count},
                ip=source_ip,
                user_agent=user_agent,
            )
    except AdminSecurityError:
        raise
    except Exception as exc:
        raise AdminSecurityError("AUDIT_UNAVAILABLE", "安全审计暂时不可用", 503) from exc
    if locked:
        raise AdminRateLimitError("ADMIN_LOGIN_LOCKED", "登录失败次数过多，请稍后再试", retry_after or 900)
    raise AdminSecurityError("ADMIN_LOGIN_FAILED", "用户名或密码错误", 401)


def authenticate(
    username: str,
    password: str,
    *,
    source_ip: str | None = None,
    user_agent: str | None = None,
    request_id: str | None = None,
) -> AdminPrincipal:
    settings = _require_enabled_and_initialized()
    source_ip = _parse_source_ip(source_ip)
    request_id = request_id or f"req_{uuid4().hex}"
    if not _ip_allowed(source_ip, settings):
        raise AdminSecurityError("ADMIN_IP_DENIED", "当前来源地址不允许访问管理后台", 403)
    try:
        normalized = normalize_username(username)
    except ValueError:
        normalized = ""
    keys = _throttle_keys(username if normalized else "invalid", source_ip)
    now = _now()
    with database.transaction() as db:
        ip_row = _throttle_row(db, keys[0])
        account_row = _throttle_row(db, keys[1])
        if _is_lock_active(ip_row, now) or _is_lock_active(account_row, now):
            retry = 900
            for row in (ip_row, account_row):
                if row and row["locked_until"]:
                    retry = max(1, int((_dt(row["locked_until"]) - now).total_seconds()))
                    break
            raise AdminRateLimitError("ADMIN_LOGIN_LOCKED", "登录失败次数过多，请稍后再试", retry)
        if ip_row and now - _dt(ip_row["window_started_at"]) < timedelta(minutes=1) and int(ip_row["failure_count"]) >= settings.login_rate_per_minute:
            retry = max(1, 60 - int((now - _dt(ip_row["window_started_at"])).total_seconds()))
            raise AdminRateLimitError("ADMIN_LOGIN_RATE_LIMITED", "登录请求过于频繁，请稍后再试", retry)
        user_row = db.execute("SELECT * FROM admin_users WHERE username=?", (normalized,)).fetchone() if normalized else None
    stored_hash = user_row["password_hash"] if user_row else _dummy_hash()
    password_ok = _verify_password_guarded(password, stored_hash)
    if not user_row or not user_row["is_active"] or not password_ok:
        # Ten account/IP failures produce the durable lock.  Rate limiting is
        # checked separately above and may return 429 earlier for a flood.
        account_count = int(account_row["failure_count"]) if account_row and now - _dt(account_row["window_started_at"]) < timedelta(minutes=1) else 0
        _login_failure(username=username if normalized else "invalid", source_ip=source_ip, request_id=request_id, user_agent=user_agent, locked=account_count + 1 >= 10)
    _load_csrf_key(settings)
    raw_secret = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_secret.encode("utf-8")).hexdigest()
    session_id = f"sess_{uuid4().hex}"
    created = _now()
    idle_expires = created + timedelta(minutes=settings.session_idle_minutes)
    absolute_expires = created + timedelta(hours=settings.session_absolute_hours)
    user_agent_digest = hash_user_agent(user_agent)
    credential_revision = user_row["updated_at"]
    with database.transaction(immediate=True) as db:
        latest_user = db.execute("SELECT * FROM admin_users WHERE user_id=?", (user_row["user_id"],)).fetchone()
        if latest_user is None or latest_user["updated_at"] != credential_revision or latest_user["password_hash"] != user_row["password_hash"] or not latest_user["is_active"]:
            # A concurrent password change/disable wins over this login.  Do
            # not create a session from credentials that are no longer the
            # current DB-authoritative value.
            user_row = None
        if user_row is None:
            pass
        else:
            user_row = latest_user
        # Expired sessions do not count towards the cap.  They remain for
        # audit retention and can be cleaned by the maintenance service.
        active_count = db.execute(
            "SELECT COUNT(*) FROM admin_sessions WHERE revoked_at IS NULL AND idle_expires_at>? AND absolute_expires_at>?",
            (_iso(created), _iso(created)),
        ).fetchone()[0]
        if user_row is None:
            pass
        elif int(active_count) >= settings.max_sessions:
            raise AdminSecurityError("ADMIN_SESSION_LIMIT", "管理会话已达到上限，请先吊销旧会话", 409)
        if user_row is not None:
            _clear_throttles(db, keys)
            version = _current_csrf_key_version(db)
            db.execute(
                """INSERT INTO admin_sessions(
                    session_id,user_id,token_hash,csrf_token_created_at,csrf_key_version,
                    csrf_generation,created_at,last_activity_at,last_request_at,
                    reauthenticated_at,idle_expires_at,absolute_expires_at,ip,user_agent_hash
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (session_id, user_row["user_id"], token_hash, _iso(created), version, 1, _iso(created), _iso(created), _iso(created), None, _iso(idle_expires), _iso(absolute_expires), source_ip, user_agent_digest),
            )
            record_audit_tx(
                db,
                action="LOGIN_SUCCESS",
                actor_id=user_row["user_id"],
                actor_name=user_row["username"],
                request_id=request_id,
                result="SUCCEEDED",
                ip=source_ip,
                user_agent=user_agent,
                detail={"session_id": session_id},
            )
            # ``updated_at`` is the credential revision used to close the
            # password-change/login race. A successful login must not
            # invalidate another concurrent login that verified the same
            # credential, so only last_login_at changes here.
            db.execute("UPDATE admin_users SET last_login_at=? WHERE user_id=?", (_iso(created), user_row["user_id"]))
            row = db.execute("SELECT s.*,u.username,u.is_active FROM admin_sessions s JOIN admin_users u ON u.user_id=s.user_id WHERE s.session_id=?", (session_id,)).fetchone()
        else:
            row = None
    if user_row is None:
        _login_failure(username=username, source_ip=source_ip, request_id=request_id, user_agent=user_agent)
    return _session_principal(row, raw_secret)


def get_me(principal: AdminPrincipal) -> AdminPrincipal:
    settings = _require_enabled_and_initialized()
    now = _now()
    with database.transaction(immediate=True) as db:
        row = _session_row(db, principal.session_secret)
        if row is None or _expired(row, now):
            if row is not None and not row["revoked_at"]:
                db.execute("UPDATE admin_sessions SET revoked_at=? WHERE session_id=? AND revoked_at IS NULL", (_iso(now), row["session_id"]))
            raise AdminSecurityError("ADMIN_SESSION_EXPIRED", "管理会话已过期，请重新登录", 401)
        if now - _dt(row["csrf_token_created_at"]) >= timedelta(minutes=settings.csrf_token_ttl_minutes):
            new_created = _iso(now)
            updated = db.execute(
                "UPDATE admin_sessions SET csrf_generation=csrf_generation+1,csrf_token_created_at=?,last_request_at=? WHERE session_id=? AND csrf_generation=? AND revoked_at IS NULL",
                (new_created, _iso(now), row["session_id"], row["csrf_generation"]),
            ).rowcount
            if updated != 1:
                row = _session_row(db, principal.session_secret)
            else:
                row = _session_row(db, principal.session_secret)
        else:
            db.execute("UPDATE admin_sessions SET last_request_at=? WHERE session_id=?", (_iso(now), row["session_id"]))
            row = _session_row(db, principal.session_secret)
    return _session_principal(row, principal.session_secret)


def touch_activity(principal: AdminPrincipal) -> AdminPrincipal:
    return validate_session(principal.session_secret, user_activity=True)


def logout_session(principal: AdminPrincipal, *, request_id: str | None = None, reason: str = "logout") -> bool:
    now = _iso(_now())
    with database.transaction(immediate=True) as db:
        row = _session_row(db, principal.session_secret)
        if row is None or row["revoked_at"]:
            return False
        db.execute("UPDATE admin_sessions SET revoked_at=? WHERE session_id=? AND revoked_at IS NULL", (now, row["session_id"]))
        record_audit_tx(
            db,
            action="LOGOUT",
            actor_id=row["user_id"],
            actor_name=row["username"],
            request_id=request_id or f"req_{uuid4().hex}",
            result="SUCCEEDED",
            reason=reason,
            target_type="admin_session",
            target_id=row["session_id"],
            ip=row["ip"],
            user_agent_hash=row["user_agent_hash"],
        )
    return True


def revoke_session(session_id: str, *, actor: AdminPrincipal | None = None, request_id: str | None = None, reason: str = "session revoke") -> bool:
    with database.transaction(immediate=True) as db:
        row = db.execute("SELECT s.*,u.username FROM admin_sessions s JOIN admin_users u ON u.user_id=s.user_id WHERE s.session_id=?", (session_id,)).fetchone()
        if row is None:
            raise AdminSecurityError("ADMIN_SESSION_NOT_FOUND", "管理会话不存在", 404)
        if row["revoked_at"]:
            return False
        now = _iso(_now())
        db.execute("UPDATE admin_sessions SET revoked_at=? WHERE session_id=? AND revoked_at IS NULL", (now, session_id))
        record_audit_tx(
            db,
            action="SESSION_REVOKE",
            actor_id=actor.user_id if actor else None,
            actor_name=actor.username if actor else "local-recovery",
            request_id=request_id or f"req_{uuid4().hex}",
            result="SUCCEEDED",
            reason=reason,
            target_type="admin_session",
            target_id=session_id,
            ip=actor.ip if actor else None,
        )
    return True


def revoke_all_other_sessions(principal: AdminPrincipal, *, request_id: str | None = None, reason: str = "revoke other sessions") -> int:
    with database.transaction(immediate=True) as db:
        now = _iso(_now())
        result = db.execute("UPDATE admin_sessions SET revoked_at=? WHERE user_id=? AND session_id<>? AND revoked_at IS NULL", (now, principal.user_id, principal.session_id))
        record_audit_tx(
            db,
            action="SESSION_REVOKE_ALL",
            actor_id=principal.user_id,
            actor_name=principal.username,
            request_id=request_id or f"req_{uuid4().hex}",
            result="SUCCEEDED",
            reason=reason,
            target_type="admin_user",
            target_id=principal.user_id,
            ip=principal.ip,
            user_agent_hash=principal.user_agent_hash,
            detail={"revoked_count": result.rowcount, "current_session_retained": True},
        )
    return int(result.rowcount)


def change_password(principal: AdminPrincipal, old_password: str, new_password: str, *, reason: str = "", request_id: str | None = None) -> PasswordChangeResult:
    try:
        # Validate the policy without holding the database write lock; the
        # actual hash is computed under the bounded password semaphore.
        if not isinstance(new_password, str) or len(new_password) < 12 or len(new_password) > 512:
            raise ValueError("password length outside policy")
    except ValueError as exc:
        raise AdminSecurityError("ADMIN_PASSWORD_POLICY", "新密码不符合安全策略", 422) from exc
    with database.connect() as read_db:
        credential = read_db.execute("SELECT * FROM admin_users WHERE user_id=?", (principal.user_id,)).fetchone()
    if credential is None or not credential["is_active"] or not _verify_password_guarded(old_password, credential["password_hash"]):
        raise AdminSecurityError("ADMIN_PASSWORD_INVALID", "当前密码错误", 401)
    # Verify the old credential before spending another PBKDF2 operation on
    # the replacement. The semaphore still bounds legitimate changes while
    # invalid attempts cannot consume that work first.
    new_hash = _hash_password_guarded(new_password)
    with database.transaction(immediate=True) as db:
        row = db.execute("SELECT * FROM admin_users WHERE user_id=?", (principal.user_id,)).fetchone()
        if row is None or not row["is_active"] or row["updated_at"] != credential["updated_at"] or row["password_hash"] != credential["password_hash"]:
            raise AdminSecurityError("ADMIN_PASSWORD_INVALID", "当前密码已变化，请重新验证", 401)
        now = _iso(_now())
        db.execute("UPDATE admin_users SET password_hash=?,updated_at=? WHERE user_id=?", (new_hash, now, principal.user_id))
        revoked = db.execute("UPDATE admin_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (now, principal.user_id)).rowcount
        record_audit_tx(
            db,
            action="ADMIN_PASSWORD_CHANGE",
            actor_id=principal.user_id,
            actor_name=principal.username,
            request_id=request_id or f"req_{uuid4().hex}",
            result="SUCCEEDED",
            reason=reason,
            target_type="admin_user",
            target_id=principal.user_id,
            ip=principal.ip,
            user_agent_hash=principal.user_agent_hash,
            detail={"revoked_sessions": revoked, "relogin_required": True},
        )
    return PasswordChangeResult()


def reauthenticate(principal: AdminPrincipal, current_password: str, *, request_id: str | None = None) -> datetime:
    source_ip = principal.ip or "unknown"
    key = f"reauth:{principal.user_id}|ip:{source_ip}"
    now = _now()
    with database.transaction() as db:
        throttle = _throttle_row(db, key)
        if _is_lock_active(throttle, now):
            retry = max(1, int((_dt(throttle["locked_until"]) - now).total_seconds()))
            raise AdminRateLimitError("ADMIN_REAUTH_RATE_LIMITED", "近期密码验证请求过于频繁，请稍后再试", retry)
        credential = db.execute("SELECT * FROM admin_users WHERE user_id=?", (principal.user_id,)).fetchone()
    if credential is None:
        raise AdminSecurityError("ADMIN_PASSWORD_INVALID", "当前密码错误", 401)
    verified = _verify_password_guarded(current_password, credential["password_hash"])
    if not verified:
        with database.transaction(immediate=True) as db:
            count = _record_throttle(db, key, principal.user_id, source_ip, now, lock=False)
            if count >= 5:
                db.execute("UPDATE admin_login_throttles SET locked_until=? WHERE throttle_key=?", (_iso(now + timedelta(minutes=15)), key))
        raise AdminSecurityError("ADMIN_PASSWORD_INVALID", "当前密码错误", 401)
    with database.transaction(immediate=True) as db:
        current = db.execute("SELECT * FROM admin_users WHERE user_id=?", (principal.user_id,)).fetchone()
        if current is None or current["updated_at"] != credential["updated_at"] or current["password_hash"] != credential["password_hash"]:
            raise AdminSecurityError("ADMIN_PASSWORD_INVALID", "当前密码已变化，请重新验证", 401)
        timestamp = _now()
        updated = db.execute(
            "UPDATE admin_sessions SET reauthenticated_at=?,last_request_at=? WHERE session_id=? AND user_id=? AND revoked_at IS NULL",
            (_iso(timestamp), _iso(timestamp), principal.session_id, principal.user_id),
        ).rowcount
        if updated != 1:
            raise AdminSecurityError("ADMIN_SESSION_INVALID", "管理会话无效", 401)
        db.execute("DELETE FROM admin_login_throttles WHERE throttle_key=?", (key,))
    return timestamp


def list_sessions(*, user_id: str | None = None, include_revoked: bool = False, limit: int = 50, offset: int = 0) -> dict[str, Any]:
    limit = max(1, min(int(limit), 200)); offset = max(0, int(offset))
    clauses: list[str] = []; params: list[Any] = []
    if user_id:
        clauses.append("s.user_id=?"); params.append(user_id)
    if not include_revoked:
        clauses.append("s.revoked_at IS NULL")
    where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
    with database.transaction() as db:
        rows = db.execute(f"SELECT s.*,u.username FROM admin_sessions s JOIN admin_users u ON u.user_id=s.user_id{where} ORDER BY s.created_at DESC,s.session_id DESC LIMIT ? OFFSET ?", (*params, limit, offset)).fetchall()
        total = db.execute(f"SELECT COUNT(*) FROM admin_sessions s{where}", params).fetchone()[0]
    items = []
    for row in rows:
        items.append(
            {
                "session_id": row["session_id"],
                "user_id": row["user_id"],
                "ip": row["ip"],
                "user_agent_hash": row["user_agent_hash"],
                "created_at": _dt(row["created_at"]),
                "last_activity_at": _dt(row["last_activity_at"]),
                "last_request_at": _dt(row["last_request_at"]),
                "idle_expires_at": _dt(row["idle_expires_at"]),
                "absolute_expires_at": _dt(row["absolute_expires_at"]),
                "revoked_at": _dt(row["revoked_at"]) if row["revoked_at"] else None,
            }
        )
    return {"items": items, "total": int(total), "limit": limit, "offset": offset, "total_is_estimate": False}


def cookie_secure(request: Request, settings: AdminSettings | None = None) -> bool:
    settings = settings or get_admin_settings()
    if request.url.scheme == "https":
        return True
    host = request.url.hostname or ""
    local = host in {"testserver", "localhost", "::1"}
    try:
        local = local or ipaddress.ip_address(host).is_loopback
    except ValueError:
        pass
    server = request.scope.get("server")
    server_host = server[0] if isinstance(server, (tuple, list)) and server else ""
    server_loopback = server_host in {"localhost", "::1"}
    try:
        server_loopback = server_loopback or ipaddress.ip_address(server_host).is_loopback
    except ValueError:
        # TestClient exposes testserver as a synthetic ASGI server.
        server_loopback = server_loopback or (server_host == "testserver" and settings.environment in {"development", "dev", "test", "testing"})
    if settings.environment in {"development", "dev", "test", "testing"} and local and server_loopback:
        return False
    raise AdminSecurityError("ADMIN_HTTPS_REQUIRED", "管理登录需要 HTTPS", 503)


def cookie_attributes(request: Request, settings: AdminSettings | None = None) -> dict[str, Any]:
    settings = settings or get_admin_settings()
    return {"max_age": settings.session_absolute_hours * 3600, "httponly": True, "secure": cookie_secure(request, settings), "samesite": "strict", "path": SESSION_COOKIE_PATH}


__all__ = [
    "AdminInitResult",
    "AdminPrincipal",
    "AdminRateLimitError",
    "AdminSecurityError",
    "AdminSettings",
    "CSRF_HEADER_NAME",
    "PasswordChangeResult",
    "SESSION_COOKIE_NAME",
    "SESSION_COOKIE_PATH",
    "authenticate",
    "allowed_origins",
    "change_password",
    "client_ip",
    "cookie_attributes",
    "cookie_secure",
    "current_admin",
    "ensure_admin_ready",
    "get_admin_settings",
    "get_me",
    "hash_password",
    "init_admin",
    "list_sessions",
    "load_session",
    "logout_session",
    "normalize_username",
    "reauthenticate",
    "require_admin",
    "require_admin_csrf",
    "require_json_content_type",
    "require_same_origin",
    "revoke_all_other_sessions",
    "revoke_session",
    "rotate_csrf_key",
    "touch_activity",
    "validate_csrf",
    "validate_session",
    "verify_admin",
    "verify_password",
]
