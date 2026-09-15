"""Aggregate non-authentication administrator routes.

All records in this module are served through the administrator session
dependency.  The data services return safe dictionaries; this router adds HTTP
validation, operation idempotency and the small number of external side effects
required by the console.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, Query, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.app.core.admin_security import AdminPrincipal, get_admin_settings, require_admin
from backend.app.core.config import get_settings, update_settings
from backend.app.core.errors import AppException
from backend.app.repositories import database
from backend.app.services import admin_cleanup, admin_metrics, audit
from backend.app.services import ppt as ppt_service
from backend.app.services import rag as rag_service_module
from backend.app.services import usage as usage_service

router = APIRouter(dependencies=[Depends(require_admin)])
_BACKGROUND_TASKS: set[asyncio.Task[Any]] = set()


def _track_background(task: asyncio.Task[Any]) -> asyncio.Task[Any]:
    _BACKGROUND_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_TASKS.discard)
    return task


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MutationRequest(_StrictModel):
    reason: str = Field(default="", max_length=500)
    confirm_text: str = Field(default="", max_length=300)
    idempotency_key: str | None = Field(default=None, max_length=200)


class BudgetLimitRequest(_StrictModel):
    expected_revision: int
    max_budget_usd: Decimal = Field(ge=0)
    reason: str = Field(default="", max_length=500)
    confirm_text: str = Field(default="", max_length=300)
    idempotency_key: str | None = Field(default=None, max_length=200)


class DatasetPurgeRequest(MutationRequest):
    scope: str = "datasets"
    dry_run: bool = False


class RagPurgeRequest(MutationRequest):
    batch_size: int = Field(default=500, ge=1, le=5_000)


class MaintenanceRequest(MutationRequest):
    scope: str | list[str] = "all"
    dry_run: bool = False


class ProbeRequest(MutationRequest):
    provider: str = Field(min_length=1, max_length=80)
    model: str = Field(min_length=1, max_length=160)
    timeout_seconds: float = Field(default=10, gt=0, le=30)


class ConfigUpdateRequest(_StrictModel):
    expected_revision: int
    values: dict[str, Any]
    reason: str = Field(default="", max_length=500)
    idempotency_key: str | None = Field(default=None, max_length=200)


class TokenRotateRequest(MutationRequest):
    # Kept optional for clients from the first preview contract.  The normal
    # flow uses /auth/reauth and the recent-session guard below; a supplied
    # password is accepted as a compatibility shortcut and immediately
    # reauthenticated before the write.
    current_password: str | None = Field(default=None, max_length=512)


class _SessionMutation(MutationRequest):
    pass


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or request.headers.get("x-request-id") or "admin_req_unknown"


def _actor(principal: AdminPrincipal) -> dict[str, str | None]:
    return {
        "actor_id": principal.user_id,
        "actor_name": principal.username,
        "ip": principal.ip,
        "user_agent": None,
    }


def _confirm(value: str, *, expected: str | None = None, required: bool = True) -> None:
    if required and not value.strip():
        raise AppException("ADMIN_CONFIRM_REQUIRED", "高风险操作需要填写确认内容", 422)
    if expected is not None and value.strip() != expected:
        raise AppException("ADMIN_CONFIRM_MISMATCH", "确认内容必须与操作目标完全一致", 422)


def _idempotency(header_value: str | None, body_value: str | None) -> str:
    value = (header_value or body_value or "").strip()
    if not value:
        raise AppException("IDEMPOTENCY_REQUIRED", "请提供Idempotency-Key", 422)
    if len(value) > 200 or any(ord(char) < 32 for char in value):
        raise AppException("IDEMPOTENCY_INVALID", "幂等键格式不合法", 422)
    return value


def _operation_dict(operation: Any) -> dict[str, Any]:
    if hasattr(operation, "as_dict"):
        value = operation.as_dict()
    elif isinstance(operation, dict):
        value = dict(operation)
    else:
        value = {key: getattr(operation, key) for key in ("operation_id", "actor_id", "kind", "scope", "state", "attempt_count", "intended", "result", "error_code", "retryable", "created_at", "updated_at") if hasattr(operation, key)}
    # request_hash and idempotency secrets are internal bookkeeping.  The
    # idempotency key itself is safe to show only when the caller owns it.
    value.pop("request_hash", None)
    return value


def _existing_operation(principal: AdminPrincipal, kind: str, key: str) -> Any | None:
    try:
        rows = __import__("backend.app.services.admin_operations", fromlist=["list_operations"]).list_operations(actor_id=principal.user_id, idempotency_key=key, limit=1, offset=0)
    except Exception as exc:
        if getattr(exc, "code", None) == "ADMIN_SCHEMA_UNAVAILABLE":
            raise
        raise AppException("ADMIN_OPERATIONS_UNAVAILABLE", "管理操作服务暂时不可用", 503) from exc
    for item in rows.get("items", []) if isinstance(rows, dict) else []:
        if getattr(item, "kind", None) == kind or (isinstance(item, dict) and item.get("kind") == kind):
            return item
    return None


def _begin(principal: AdminPrincipal, request: Request, *, kind: str, scope: str, intended: dict[str, Any], key: str, reason: str = "", target_type: str | None = None, target_id: str | None = None, action: str | None = None) -> Any:
    existing = _existing_operation(principal, kind, key)
    try:
        from backend.app.services.admin_operations import begin_operation

        # Always delegate to the operation service, including when a row was
        # found above.  It recomputes request_hash and rejects a reused key
        # whose target or payload changed.
        operation = begin_operation(**{**_actor(principal), "kind": kind, "scope": scope, "intended": intended, "request_id": _request_id(request), "idempotency_key": key, "reason": reason, "target_type": target_type, "target_id": target_id, "action": action})
        if existing is not None and getattr(operation, "operation_id", None) != getattr(existing, "operation_id", None):
            raise AppException("IDEMPOTENCY_CONFLICT", "幂等键已用于其他操作", 409)
        return operation
    except AppException:
        raise
    except Exception as exc:
        raise AppException("ADMIN_OPERATIONS_UNAVAILABLE", "管理操作服务暂时不可用", 503) from exc


def _mark_running(operation: Any) -> Any:
    if getattr(operation, "state", None) != "pending":
        return operation
    try:
        from backend.app.services.admin_operations import mark_operation_running

        return mark_operation_running(operation.operation_id)
    except AppException:
        raise
    except Exception as exc:
        raise AppException("ADMIN_OPERATIONS_UNAVAILABLE", "管理操作服务暂时不可用", 503) from exc


def _complete(principal: AdminPrincipal, request: Request, operation: Any, *, result: dict[str, Any] | None = None, state: str = "succeeded", error_code: str | None = None, reason: str = "", action: str | None = None) -> Any:
    try:
        from backend.app.services.admin_operations import complete_operation

        return complete_operation(operation.operation_id, **{**_actor(principal), "request_id": _request_id(request), "result": result, "state": state, "error_code": error_code, "reason": reason, "action": action})
    except AppException:
        raise
    except Exception as exc:
        raise AppException("AUDIT_UNAVAILABLE", "管理操作结果无法写入审计", 503) from exc


def _operation_is_existing(operation: Any, principal: AdminPrincipal, kind: str, key: str) -> bool:
    existing = _existing_operation(principal, kind, key)
    return existing is not None and getattr(existing, "operation_id", None) == getattr(operation, "operation_id", None)


def _require_recent_reauth(principal: AdminPrincipal, *, max_age_seconds: int = 300) -> None:
    """Require a password check recorded on this live admin session."""

    db = database.connect()
    try:
        row = db.execute("SELECT reauthenticated_at,revoked_at FROM admin_sessions WHERE session_id=? AND user_id=?", (principal.session_id, principal.user_id)).fetchone()
    finally:
        db.close()
    if not row or row["revoked_at"] is not None or not row["reauthenticated_at"]:
        raise AppException("ADMIN_REAUTH_REQUIRED", "该操作需要五分钟内的密码验证", 403)
    raw = str(row["reauthenticated_at"])
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        timestamp = datetime.fromisoformat(raw)
        timestamp = timestamp.replace(tzinfo=UTC) if timestamp.tzinfo is None else timestamp.astimezone(UTC)
    except ValueError as exc:
        raise AppException("ADMIN_REAUTH_REQUIRED", "该操作需要五分钟内的密码验证", 403) from exc
    if (datetime.now(UTC) - timestamp).total_seconds() > max_age_seconds:
        raise AppException("ADMIN_REAUTH_REQUIRED", "该操作需要五分钟内的密码验证", 403)


def _assert_session_operation_available(db: Any, session_id: str, operation_id: str) -> None:
    """Serialize force-end and lease-recovery intents for one session."""

    row = db.execute(
        "SELECT operation_id FROM admin_operations WHERE scope=? AND operation_id<>? AND kind IN ('discussion_force_end','discussion_lease_recover') AND state IN ('pending','running') LIMIT 1",
        (session_id, operation_id),
    ).fetchone()
    if row:
        raise AppException("DISCUSSION_OPERATION_CONFLICT", "该会话已有管理操作正在执行", 409)


def _assert_scope_operation_available(db: Any, scope: str, operation_id: str, kinds: tuple[str, ...], *, code: str = "ADMIN_OPERATION_CONFLICT") -> None:
    placeholders = ",".join("?" for _ in kinds)
    row = db.execute(
        f"SELECT operation_id FROM admin_operations WHERE scope=? AND operation_id<>? AND kind IN ({placeholders}) AND state IN ('pending','running') LIMIT 1",
        [scope, operation_id, *kinds],
    ).fetchone()
    if row:
        raise AppException(code, "该目标已有管理操作正在执行", 409)


def _claim_scoped_operation(operation: Any, scope: str, kinds: tuple[str, ...], *, code: str = "ADMIN_OPERATION_CONFLICT") -> Any:
    from backend.app.services.admin_operations import mark_operation_running_tx

    with database.transaction(immediate=True) as db:
        _assert_scope_operation_available(db, scope, operation.operation_id, kinds, code=code)
        return mark_operation_running_tx(db, operation.operation_id)


def _retry_target_text(operation: Any) -> str:
    intended = operation.intended if hasattr(operation, "intended") else (operation.get("intended") or {})
    for key in ("dataset_id", "session_id", "file_id", "document_id", "project_id", "scope", "field"):
        if isinstance(intended, dict) and intended.get(key):
            value = intended[key]
            if key == "scope" and isinstance(value, (list, tuple)):
                return ",".join(str(item) for item in value)
            return str(value)
    return str(getattr(operation, "scope", "") or (operation.get("scope", "") if isinstance(operation, dict) else ""))


def _config_field_source(key: str) -> str:
    return "env_override" if key in os.environ else "file_or_default"


_CONFIG_FIELDS = (
    ("LLM_PROVIDER", "模型服务商", False, False),
    ("OPENAI_BASE_URL", "模型服务地址", False, True),
    ("OPENAI_MODEL", "模型名称", False, False),
    ("EMBEDDING_MODEL", "向量模型", False, False),
    ("USE_LOCAL_LLM", "使用本地模型", False, True),
    ("LOCAL_LLM_URL", "本地模型地址", False, True),
    ("LOCAL_LLM_MODEL", "本地模型名称", False, False),
    ("MAX_BUDGET_USD", "模型预算上限", False, False),
    ("LLM_MAX_OUTPUT_TOKENS", "最大输出Token", False, True),
    ("UNKNOWN_MODEL_RESERVE_USD", "未知模型预留金额", False, False),
    ("OPENAI_API_KEY", "主模型密钥", True, False),
    ("TAVILY_API_KEY", "搜索服务密钥", True, False),
    ("ROLE_MODELS", "角色模型配置", False, True),
    ("PROVIDER_CREDENTIALS", "服务商凭据配置", True, True),
)


def _config_view() -> dict[str, Any]:
    settings = get_settings()
    fields: list[dict[str, Any]] = []
    for key, label, secret, restart in _CONFIG_FIELDS:
        raw = getattr(settings, key, None)
        if secret:
            value: Any = {"configured": bool(raw)}
        elif key == "ROLE_MODELS":
            try:
                value = json.loads(raw or "{}")
            except (TypeError, ValueError):
                value = {}
        elif key == "PROVIDER_CREDENTIALS":
            value = {"configured": bool(raw)}
        else:
            value = raw
        fields.append({"key": key, "value": value, "label": label, "source": _config_field_source(key), "editable": key not in os.environ, "requires_restart": restart, "secret": secret})
    return {"revision": int(settings.CONFIG_REVISION), "fields": fields}


def _sanitize_config_values(values: dict[str, Any]) -> dict[str, Any]:
    allowed = {key for key, *_ in _CONFIG_FIELDS}
    normalized = {str(key).upper(): value for key, value in values.items()}
    unknown = sorted(set(normalized) - allowed)
    if unknown:
        raise AppException("CONFIG_FIELD_INVALID", f"不允许修改的配置项: {', '.join(unknown)}", 422)
    # Reuse the business endpoint's provider/role validators and SSRF guard.
    from backend.app.api.endpoints import config as config_endpoint

    cleaned: dict[str, Any] = {}
    for key, value in normalized.items():
        if key.endswith("_KEY") and value is not None:
            value = str(value).strip()
        if key in {"OPENAI_BASE_URL", "LOCAL_LLM_URL"} and value:
            from backend.app.core.security import validate_outbound_base_url

            value = validate_outbound_base_url(str(value), allow_private=key == "LOCAL_LLM_URL")
        if key == "ROLE_MODELS":
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (TypeError, ValueError) as exc:
                    raise AppException("CONFIG_INVALID", "ROLE_MODELS必须是合法JSON", 422) from exc
            if not isinstance(value, dict):
                raise AppException("CONFIG_INVALID", "ROLE_MODELS必须是对象", 422)
            value = json.dumps(config_endpoint._sanitize_role_models(value), ensure_ascii=False)
        if key == "PROVIDER_CREDENTIALS":
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except (TypeError, ValueError) as exc:
                    raise AppException("CONFIG_INVALID", "PROVIDER_CREDENTIALS必须是合法JSON", 422) from exc
            if not isinstance(value, dict):
                raise AppException("CONFIG_INVALID", "PROVIDER_CREDENTIALS必须是对象", 422)
            # _merge_credentials expects ProviderCredentialInput-like values;
            # convert dictionaries through the public model where possible.
            from backend.app.models.contracts import ProviderCredentialInput

            value = json.dumps(config_endpoint._merge_credentials({key: ProviderCredentialInput.model_validate(item) for key, item in value.items()}), ensure_ascii=False)
        cleaned[key] = value
    return cleaned


@router.get("/dashboard/overview")
def dashboard_overview(response: Response):
    result = admin_metrics.dashboard_overview()
    _no_store(response)
    return result


@router.get("/dashboard/trends")
def dashboard_trends(response: Response, range_name: str = Query("24h", alias="range"), metric: str = Query("cost"), provider: str | None = None, model: str | None = None):
    result = {"items": admin_metrics.usage_trends(range_name, metric, provider=provider, model=model)}
    _no_store(response)
    return result


@router.get("/dashboard/activity")
def dashboard_activity(response: Response, level: str | None = None, category: str | None = None, limit: int = 50, offset: int = 0):
    result = admin_metrics.activity_events(level=level, category=category, limit=limit, offset=offset)
    _no_store(response)
    return result


@router.get("/usage/summary")
def usage_summary(response: Response, range_name: str = Query("24h", alias="range"), from_: str | None = Query(None, alias="from"), to: str | None = None):
    result = admin_metrics.usage_summary(range_name, from_=from_, to=to)
    _no_store(response)
    return result


@router.get("/usage/by-model")
def usage_by_model(response: Response, range_name: str = Query("24h", alias="range"), from_: str | None = Query(None, alias="from"), to: str | None = None, provider: str | None = None, model: str | None = None, limit: int = 50, offset: int = 0):
    result = admin_metrics.usage_by_model(range_name, from_=from_, to=to, provider=provider, model=model, limit=limit, offset=offset)
    _no_store(response)
    return result


@router.get("/budget/reservations")
def budget_reservations(response: Response, status: str | None = None, range_name: str | None = Query(None, alias="range"), from_: str | None = Query(None, alias="from"), to: str | None = None, limit: int = 50, offset: int = 0):
    result = admin_metrics.reservation_views(status=status, range_name=range_name, from_=from_, to=to, limit=limit, offset=offset)
    _no_store(response)
    return result


@router.post("/budget/reset-overrun")
def reset_budget_overrun(request: Request, response: Response, body: MutationRequest, idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    _confirm(body.confirm_text, expected="provider_overrun")
    _require_recent_reauth(principal)
    key = _idempotency(idempotency_header, body.idempotency_key)
    operation = _begin(principal, request, kind="overrun_reset", scope="provider_overrun", intended={"scope": "provider_overrun"}, key=key, reason=body.reason, target_type="budget", target_id="provider_overrun")
    if getattr(operation, "state", None) != "pending":
        _no_store(response)
        return _operation_dict(operation)
    operation = _mark_running(operation)
    try:
        cleared = usage_service.reset_provider_overrun()
        operation = _complete(principal, request, operation, result={"cleared_count": int(cleared), "unknown_holds_retained": True}, reason=body.reason)
    except AppException as exc:
        operation = _complete(principal, request, operation, state="failed", error_code=exc.code, reason=body.reason)
        raise
    except Exception as exc:
        operation = _complete(principal, request, operation, state="failed", error_code="OVERRUN_RESET_FAILED", reason=body.reason)
        raise AppException("OVERRUN_RESET_FAILED", "预算超额状态复位失败", 503) from exc
    _no_store(response)
    return _operation_dict(operation)


@router.put("/budget/limit")
def update_budget_limit(request: Request, response: Response, body: BudgetLimitRequest, idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    _confirm(body.confirm_text, expected="MAX_BUDGET_USD")
    _require_recent_reauth(principal)
    key = _idempotency(idempotency_header, body.idempotency_key)
    intended = {"field": "MAX_BUDGET_USD", "max_budget_usd": str(body.max_budget_usd), "expected_revision": body.expected_revision}
    operation = _begin(principal, request, kind="budget_limit_update", scope="MAX_BUDGET_USD", intended=intended, key=key, reason=body.reason, target_type="budget", target_id="MAX_BUDGET_USD")
    if getattr(operation, "state", None) != "pending":
        _no_store(response)
        return _operation_dict(operation)
    operation = _mark_running(operation)
    try:
        updated = update_settings({"MAX_BUDGET_USD": body.max_budget_usd}, expected_revision=body.expected_revision)
        operation = _complete(principal, request, operation, result={"revision": int(updated.CONFIG_REVISION), "max_budget_usd": str(updated.MAX_BUDGET_USD)}, reason=body.reason)
    except AppException as exc:
        operation = _complete(principal, request, operation, state="failed", error_code=exc.code, reason=body.reason)
        raise
    except (TypeError, ValueError) as exc:
        operation = _complete(principal, request, operation, state="failed", error_code="BUDGET_LIMIT_INVALID", reason=body.reason)
        raise AppException("BUDGET_LIMIT_INVALID", "预算上限不合法", 422) from exc
    _no_store(response)
    return _operation_dict(operation)


@router.get("/usage/export.csv")
def usage_export(response: Response, range_name: str = Query("24h", alias="range"), from_: str | None = Query(None, alias="from"), to: str | None = None, provider: str | None = None, model: str | None = None, scope: str = "filtered"):
    if scope not in {"filtered", "all"}:
        raise AppException("ADMIN_EXPORT_SCOPE_INVALID", "CSV导出范围不合法", 422)
    rows = admin_metrics.usage_export_rows("all" if scope == "all" else range_name, from_=from_, to=to, provider=provider, model=model)
    output = StreamingResponse(content=admin_metrics.stream_usage_csv(rows), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="usage-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.csv"'})
    _no_store(output)
    return output


@router.get("/datasets")
def datasets(response: Response, expired: bool | None = None, limit: int = 50, offset: int = 0):
    result = admin_metrics.list_datasets(expired=expired, limit=limit, offset=offset)
    _no_store(response)
    return result


@router.get("/datasets/{dataset_id}")
def dataset(dataset_id: str, response: Response):
    result = admin_metrics.dataset_detail(dataset_id)
    _no_store(response)
    return result


@router.delete("/datasets/{dataset_id}")
def delete_dataset(dataset_id: str, request: Request, response: Response, body: MutationRequest = Body(...), idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    _confirm(body.confirm_text, expected=dataset_id)
    _require_recent_reauth(principal)
    key = _idempotency(idempotency_header, body.idempotency_key)
    operation = _begin(principal, request, kind="dataset_delete", scope=dataset_id, intended={"dataset_id": dataset_id}, key=key, reason=body.reason, target_type="dataset", target_id=dataset_id)
    if getattr(operation, "state", None) != "pending":
        _no_store(response)
        return _operation_dict(operation)
    try:
        from backend.app.services.admin_operations import complete_operation_tx, mark_operation_running_tx

        with database.transaction(immediate=True) as db:
            # The operation was already created by _begin; update it and the
            # dataset in one transaction only after idempotency has passed.
            _assert_scope_operation_available(db, dataset_id, operation.operation_id, ("dataset_delete",), code="DATASET_OPERATION_CONFLICT")
            mark_operation_running_tx(db, operation.operation_id)
            result = admin_cleanup.delete_dataset_tx(db, dataset_id)
            operation = complete_operation_tx(db, operation.operation_id, **{**_actor(principal), "request_id": _request_id(request), "result": result, "state": "succeeded", "reason": body.reason})
    except AppException as exc:
        try:
            if getattr(operation, "state", None) in {"pending", "running"}:
                operation = _complete(principal, request, operation, state="failed", error_code=exc.code, reason=body.reason)
        except Exception:
            pass
        raise
    _no_store(response)
    return _operation_dict(operation)


@router.post("/datasets/purge-expired")
def purge_datasets(request: Request, response: Response, body: DatasetPurgeRequest, idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    _confirm(body.confirm_text, expected=body.scope)
    _require_recent_reauth(principal)
    if body.scope != "datasets":
        raise AppException("MAINTENANCE_SCOPE_INVALID", "该接口只能清理datasets范围", 422)
    key = _idempotency(idempotency_header, body.idempotency_key)
    cutoff = datetime.now(UTC)
    previous = _existing_operation(principal, "dataset_purge", key)
    if previous is not None:
        previous_intended = getattr(previous, "intended", {}) if not isinstance(previous, dict) else previous.get("intended", {})
        raw_cutoff = previous_intended.get("cutoff") if isinstance(previous_intended, dict) else None
        if raw_cutoff:
            try:
                cutoff = datetime.fromisoformat(str(raw_cutoff).replace("Z", "+00:00"))
                cutoff = cutoff.replace(tzinfo=UTC) if cutoff.tzinfo is None else cutoff.astimezone(UTC)
            except ValueError:
                pass
    operation = _begin(principal, request, kind="dataset_purge", scope="datasets", intended={"scope": "datasets", "dry_run": body.dry_run, "cutoff": cutoff.isoformat()}, key=key, reason=body.reason)
    if getattr(operation, "state", None) != "pending":
        _no_store(response)
        return _operation_dict(operation)
    operation = _claim_scoped_operation(operation, "datasets", ("dataset_purge",), code="DATASET_OPERATION_CONFLICT")
    try:
        result = admin_cleanup.purge_expired_datasets(dry_run=body.dry_run, now=cutoff)
        partial = bool(int(result.get("failed", 0) or 0) or int(result.get("unknown", 0) or 0))
        operation = _complete(
            principal,
            request,
            operation,
            result=result,
            state="partial" if partial else "succeeded",
            error_code="DATASET_PURGE_PARTIAL" if partial else None,
            reason=body.reason,
        )
    except AppException as exc:
        operation = _complete(principal, request, operation, state="failed", error_code=exc.code, reason=body.reason)
        raise
    _no_store(response)
    return _operation_dict(operation)


@router.get("/discussions")
def discussions(response: Response, status: str | None = None, active: bool | None = None, limit: int = 50, offset: int = 0):
    result = admin_metrics.list_discussions(status=status, active=active, limit=limit, offset=offset)
    _no_store(response)
    return result


@router.get("/discussions/{session_id}/events")
def discussion_event_list(session_id: str, response: Response, after_seq: int = 0, limit: int = 50, offset: int = 0):
    result = admin_metrics.discussion_events(session_id, after_seq=after_seq, limit=limit, offset=offset)
    _no_store(response)
    return result


@router.get("/discussions/{session_id}/commands")
def discussion_command_list(session_id: str, response: Response, status: str | None = None, limit: int = 50, offset: int = 0):
    result = admin_metrics.discussion_commands(session_id, status=status, limit=limit, offset=offset)
    _no_store(response)
    return result


@router.post("/discussions/{session_id}/force-end")
def force_end_discussion(session_id: str, request: Request, response: Response, body: MutationRequest, idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    _confirm(body.confirm_text, expected=session_id)
    _require_recent_reauth(principal)
    key = _idempotency(idempotency_header, body.idempotency_key)
    operation = _begin(principal, request, kind="discussion_force_end", scope=session_id, intended={"session_id": session_id}, key=key, reason=body.reason, target_type="discussion", target_id=session_id)
    if getattr(operation, "state", None) != "pending":
        _no_store(response)
        return _operation_dict(operation)
    try:
        from backend.app.services.admin_operations import complete_operation_tx, mark_operation_running_tx
        from backend.app.services.discussion_session import admin_cancel

        with database.transaction(immediate=True) as db:
            _assert_session_operation_available(db, session_id, operation.operation_id)
            mark_operation_running_tx(db, operation.operation_id)
            result = admin_cancel(db, session_id)
            operation = complete_operation_tx(db, operation.operation_id, **{**_actor(principal), "request_id": _request_id(request), "result": result, "state": "succeeded", "reason": body.reason})
    except AppException as exc:
        try:
            if getattr(operation, "state", None) in {"pending", "running"}:
                operation = _complete(principal, request, operation, state="failed", error_code=exc.code, reason=body.reason)
        except Exception:
            pass
        raise
    _no_store(response)
    return _operation_dict(operation)


@router.post("/discussions/{session_id}/lease-recover")
async def recover_discussion(session_id: str, request: Request, response: Response, body: MutationRequest, idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    _confirm(body.confirm_text, expected=session_id)
    _require_recent_reauth(principal)
    key = _idempotency(idempotency_header, body.idempotency_key)
    operation = _begin(principal, request, kind="discussion_lease_recover", scope=session_id, intended={"session_id": session_id}, key=key, reason=body.reason, target_type="discussion", target_id=session_id)
    if getattr(operation, "state", None) != "pending":
        _no_store(response)
        return _operation_dict(operation)
    try:
        from backend.app.services.admin_operations import complete_operation
        from backend.app.services.discussion_session import admin_recover, run_admin_recovery

        with database.transaction(immediate=True) as db:
            from backend.app.services.admin_operations import mark_operation_running_tx

            _assert_session_operation_available(db, session_id, operation.operation_id)
            operation = mark_operation_running_tx(db, operation.operation_id)
            commands = admin_recover(db, session_id)

        async def worker() -> None:
            try:
                await run_admin_recovery(commands)
                await asyncio.to_thread(complete_operation, operation.operation_id, **{**_actor(principal), "request_id": _request_id(request), "result": {"session_id": session_id, "queued_commands": len(commands)}, "state": "succeeded", "reason": body.reason})
            except Exception as exc:
                try:
                    await asyncio.to_thread(complete_operation, operation.operation_id, **{**_actor(principal), "request_id": _request_id(request), "result": {"session_id": session_id}, "state": "failed", "error_code": getattr(exc, "code", type(exc).__name__), "reason": body.reason})
                except Exception:
                    pass

        _track_background(asyncio.create_task(worker()))
        _no_store(response)
        response.status_code = 202
        return _operation_dict(operation)
    except AppException as exc:
        try:
            if getattr(operation, "state", None) in {"pending", "running"}:
                operation = await asyncio.to_thread(_complete, principal, request, operation, state="failed", error_code=exc.code, reason=body.reason)
        except Exception:
            pass
        raise


@router.get("/files")
def files(response: Response, kind: str | None = None, status: str | None = None, limit: int = 50, offset: int = 0):
    result = admin_metrics.list_files(kind=kind, status=status, limit=limit, offset=offset)
    _no_store(response)
    return result


@router.get("/ppts")
def ppts(response: Response, status: str | None = None, limit: int = 50, offset: int = 0):
    result = admin_metrics.list_files(kind="ppt", status=status, limit=limit, offset=offset)
    _no_store(response)
    return result


@router.get("/ppts/{file_id}/download")
def download_ppt(file_id: str, response: Response):
    path, display_name = ppt_service.resolve_download(file_id)
    _no_store(response)
    return FileResponse(path, filename=display_name, media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation", headers={"Cache-Control": "no-store", "Pragma": "no-cache"})


@router.delete("/ppts/{file_id}")
def delete_ppt(file_id: str, request: Request, response: Response, body: MutationRequest, idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    _confirm(body.confirm_text, expected=file_id)
    _require_recent_reauth(principal)
    key = _idempotency(idempotency_header, body.idempotency_key)
    operation = _begin(principal, request, kind="ppt_delete", scope=file_id, intended={"file_id": file_id}, key=key, reason=body.reason, target_type="file", target_id=file_id)
    if getattr(operation, "state", None) != "pending":
        _no_store(response)
        return _operation_dict(operation)
    operation = _claim_scoped_operation(operation, file_id, ("ppt_delete",), code="FILE_OPERATION_CONFLICT")
    try:
        db = database.connect()
        try:
            row = db.execute("SELECT file_id,disk_path,display_name FROM files WHERE file_id=?", (file_id,)).fetchone()
        finally:
            db.close()
        if not row:
            raise AppException("FILE_NOT_FOUND", "文件登记不存在", 404)
        path = Path(str(row["disk_path"])).resolve()
        output = Path(ppt_service.OUTPUT_DIR).resolve()
        if os.path.commonpath([str(path), str(output)]) != str(output):
            raise AppException("FILE_PATH_INVALID", "文件路径不在成果目录内", 400)
        if not path.is_file():
            result = {"file_id": file_id, "status": "partial", "deleted": False, "integrity_status": "missing"}
            operation = _complete(principal, request, operation, result=result, state="partial", error_code="FILE_MISSING", reason=body.reason)
        else:
            path.unlink()
            with database.transaction(immediate=True) as db:
                db.execute("DELETE FROM files WHERE file_id=?", (file_id,))
            result = {"file_id": file_id, "deleted": True}
            operation = _complete(principal, request, operation, result=result, reason=body.reason)
    except AppException as exc:
        if getattr(operation, "state", None) in {"pending", "running"}:
            _complete(principal, request, operation, state="failed", error_code=exc.code, reason=body.reason)
        raise
    except OSError as exc:
        _complete(principal, request, operation, state="partial", error_code="FILE_DELETE_FAILED", reason=body.reason)
        raise AppException("FILE_DELETE_FAILED", "文件删除失败，登记记录已保留", 409) from exc
    _no_store(response)
    return _operation_dict(operation)


@router.get("/rag/projects")
async def rag_projects(response: Response, limit: int = 50, offset: int = 0):
    result = await admin_metrics.rag_projects(limit=limit, offset=offset)
    _no_store(response)
    return result


@router.get("/rag/projects/{project_id}/documents")
async def rag_documents(project_id: str, response: Response, filename: str | None = None, limit: int = 50, offset: int = 0):
    result = await admin_metrics.rag_documents(project_id, filename=filename, limit=limit, offset=offset)
    _no_store(response)
    return result


@router.get("/rag/collections")
async def rag_collections(response: Response):
    result = await admin_metrics.rag_collections()
    _no_store(response)
    return result


@router.delete("/rag/projects/{project_id}/documents/{document_id}")
async def delete_rag_document(project_id: str, document_id: str, request: Request, response: Response, body: MutationRequest, idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    _confirm(body.confirm_text, expected=document_id)
    _require_recent_reauth(principal)
    key = _idempotency(idempotency_header, body.idempotency_key)
    operation = _begin(principal, request, kind="rag_document_delete", scope=project_id, intended={"project_id": project_id, "document_id": document_id}, key=key, reason=body.reason, target_type="rag_document", target_id=document_id)
    if getattr(operation, "state", None) != "pending":
        _no_store(response)
        return _operation_dict(operation)
    operation = _claim_scoped_operation(operation, project_id, ("rag_document_delete", "rag_project_purge"), code="RAG_OPERATION_CONFLICT")

    async def worker() -> tuple[dict[str, Any] | None, Exception | None, Any | None]:
        try:
            result = await rag_service_module.rag_service.admin_delete(project_id, document_id)
            state = "partial" if result.get("status") == "partial" else "succeeded"
            completed = await asyncio.to_thread(_complete, principal, request, operation, result=result, state=state, error_code="RAG_PARTIAL" if state == "partial" else None, reason=body.reason)
            return result, None, completed
        except Exception as exc:  # completion below preserves the real error code
            try:
                await asyncio.to_thread(_complete, principal, request, operation, state="failed", error_code=getattr(exc, "code", "RAG_DELETE_FAILED"), reason=body.reason)
            except Exception:
                pass
            return None, exc, None

    task = _track_background(asyncio.create_task(worker()))
    try:
        result, error, completed = await asyncio.wait_for(asyncio.shield(task), timeout=3.0)
    except asyncio.TimeoutError:
        _no_store(response)
        response.status_code = 202
        return _operation_dict(operation)
    if error is not None:
        if isinstance(error, AppException):
            raise error
        raise AppException("RAG_DELETE_FAILED", "项目知识库删除失败，请查询操作后重试", 503) from error
    result = result or {}
    operation = completed or operation
    _no_store(response)
    return _operation_dict(operation)


@router.post("/rag/projects/{project_id}/purge")
async def purge_rag_project(project_id: str, request: Request, response: Response, body: RagPurgeRequest, idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    _confirm(body.confirm_text, expected=project_id)
    _require_recent_reauth(principal)
    key = _idempotency(idempotency_header, body.idempotency_key)
    operation = _begin(principal, request, kind="rag_project_purge", scope=project_id, intended={"project_id": project_id, "batch_size": body.batch_size}, key=key, reason=body.reason, target_type="rag_project", target_id=project_id)
    if getattr(operation, "state", None) != "pending":
        _no_store(response)
        return _operation_dict(operation)
    operation = _claim_scoped_operation(operation, project_id, ("rag_document_delete", "rag_project_purge"), code="RAG_OPERATION_CONFLICT")

    async def worker() -> tuple[dict[str, Any] | None, Exception | None, Any | None]:
        try:
            result = await rag_service_module.rag_service.admin_delete(project_id)
            state = "partial" if result.get("status") == "partial" else "succeeded"
            completed = await asyncio.to_thread(_complete, principal, request, operation, result=result, state=state, error_code="RAG_PARTIAL" if state == "partial" else None, reason=body.reason)
            return result, None, completed
        except Exception as exc:
            try:
                await asyncio.to_thread(_complete, principal, request, operation, state="failed", error_code=getattr(exc, "code", "RAG_PURGE_FAILED"), reason=body.reason)
            except Exception:
                pass
            return None, exc, None

    task = _track_background(asyncio.create_task(worker()))
    try:
        result, error, completed = await asyncio.wait_for(asyncio.shield(task), timeout=3.0)
    except asyncio.TimeoutError:
        _no_store(response)
        response.status_code = 202
        return _operation_dict(operation)
    if error is not None:
        if isinstance(error, AppException):
            raise error
        raise AppException("RAG_PURGE_FAILED", "项目知识库清理失败，请查询操作后重试", 503) from error
    result = result or {}
    operation = completed or operation
    _no_store(response)
    return _operation_dict(operation)


@router.get("/system/health")
def system_health(response: Response):
    result = admin_metrics.health_view()
    _no_store(response)
    return result


@router.get("/system/storage")
def system_storage(response: Response):
    result = admin_metrics.storage_view()
    _no_store(response)
    return result


@router.get("/system/logs")
def system_logs(response: Response, level: str | None = None, tail: int = 200, cursor: str | None = None, max_bytes: int = admin_metrics.MAX_LOG_BYTES, include_rotated: bool = False):
    result = admin_metrics.read_logs(level=level, tail=tail, cursor=cursor, max_bytes=max_bytes, include_rotated=include_rotated)
    _no_store(response)
    return result


@router.post("/system/maintenance")
async def system_maintenance(request: Request, response: Response, body: MaintenanceRequest, idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    expected_scope = ",".join(body.scope) if isinstance(body.scope, list) else str(body.scope)
    _confirm(body.confirm_text, expected=expected_scope)
    _require_recent_reauth(principal)
    key = _idempotency(idempotency_header, body.idempotency_key)
    scopes = body.scope
    previous = _existing_operation(principal, "maintenance", key)
    cutoff = datetime.now(UTC)
    if previous is not None:
        previous_intended = getattr(previous, "intended", {}) if not isinstance(previous, dict) else previous.get("intended", {})
        raw_cutoff = previous_intended.get("cutoff") if isinstance(previous_intended, dict) else None
        if raw_cutoff:
            try:
                cutoff = datetime.fromisoformat(str(raw_cutoff).replace("Z", "+00:00"))
                cutoff = cutoff.replace(tzinfo=UTC) if cutoff.tzinfo is None else cutoff.astimezone(UTC)
            except ValueError:
                pass
    operation = _begin(principal, request, kind="maintenance", scope=",".join(scopes) if isinstance(scopes, list) else str(scopes), intended={"scope": scopes, "dry_run": body.dry_run, "cutoff": cutoff.isoformat()}, key=key, reason=body.reason)
    if getattr(operation, "state", None) != "pending":
        _no_store(response)
        return _operation_dict(operation)
    operation = _mark_running(operation)

    async def worker() -> tuple[dict[str, Any] | None, Exception | None, Any | None]:
        try:
            result = await asyncio.to_thread(admin_cleanup.run_cleanup, scopes=scopes, dry_run=body.dry_run, now=cutoff)
            failed = any(int(item.get("failed", 0)) > 0 for item in result.get("scopes", {}).values())
            unknown = any(int(item.get("unknown", 0)) > 0 for item in result.get("scopes", {}).values())
            state = "partial" if failed or unknown else "succeeded"
            completed = await asyncio.to_thread(_complete, principal, request, operation, result=result, state=state, error_code="MAINTENANCE_PARTIAL" if state == "partial" else None, reason=body.reason)
            return result, None, completed
        except Exception as exc:
            try:
                await asyncio.to_thread(_complete, principal, request, operation, state="failed", error_code=getattr(exc, "code", "MAINTENANCE_FAILED"), reason=body.reason)
            except Exception:
                pass
            return None, exc, None

    task = _track_background(asyncio.create_task(worker()))
    try:
        result, error, completed = await asyncio.wait_for(asyncio.shield(task), timeout=3.0)
    except asyncio.TimeoutError:
        _no_store(response)
        response.status_code = 202
        return _operation_dict(operation)
    if error is not None:
        if isinstance(error, AppException):
            raise error
        raise AppException("MAINTENANCE_FAILED", "维护任务执行失败，请查询操作详情", 503) from error
    result = result or {}
    operation = completed or operation
    _no_store(response)
    return _operation_dict(operation)


@router.get("/system/maintenance/{operation_id}")
def maintenance_operation(operation_id: str, response: Response, principal: AdminPrincipal = Depends(require_admin)):
    return operation(operation_id, response, principal)


@router.post("/system/probe/llm")
async def probe_llm(request: Request, response: Response, body: ProbeRequest, idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    _confirm(body.confirm_text, expected=f"{body.provider}/{body.model}")
    _require_recent_reauth(principal)
    key = _idempotency(idempotency_header, body.idempotency_key)
    operation = _begin(principal, request, kind="llm_probe", scope=f"{body.provider}/{body.model}", intended={"provider": body.provider, "model": body.model}, key=key, reason=body.reason)
    if getattr(operation, "state", None) != "pending":
        _no_store(response)
        return _operation_dict(operation)
    operation = _mark_running(operation)
    started = time.perf_counter()
    reservation = None
    request_token = f"admin_probe_{secrets.token_hex(12)}"
    local = body.provider in {"local", "ollama"}
    try:
        from backend.app.core.clients import clear_client_cache
        from backend.app.core.security import outbound_http_clients, validate_outbound_base_url
        from backend.app.services.model_providers import get_provider

        settings = get_settings()
        provider_info = get_provider("ollama" if local else body.provider)
        stored_credentials: dict[str, Any] = {}
        if not local and settings.PROVIDER_CREDENTIALS:
            try:
                parsed_credentials = json.loads(settings.PROVIDER_CREDENTIALS)
                candidate = parsed_credentials.get(body.provider, {}) if isinstance(parsed_credentials, dict) else {}
                stored_credentials = candidate if isinstance(candidate, dict) else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                stored_credentials = {}
        base_url = settings.LOCAL_LLM_URL if local else (stored_credentials.get("base_url") or (settings.OPENAI_BASE_URL if body.provider == settings.LLM_PROVIDER else provider_info.base_url))
        base_url = validate_outbound_base_url(str(base_url), allow_private=local)
        # A provider-specific credential is bound to its configured endpoint;
        # never send the active provider's key to a different provider.
        if local:
            api_key = "ollama"
        else:
            from backend.app.api.endpoints import config as config_endpoint

            api_key = config_endpoint._bound_key(body.provider, base_url, None)
        if not api_key:
            raise AppException("LLM_NOT_CONFIGURED", "缺少模型服务 API Key", 400)
        reservation = usage_service.reserve(request_token, "local" if local else body.provider, body.model, "admin probe")
        usage_service.mark_dispatched(reservation)
        headers = {} if local else ({"x-api-key": api_key, "anthropic-version": "2023-06-01"} if provider_info.api_style == "anthropic" else {"Authorization": f"Bearer {api_key}"})
        sync_client, async_client = outbound_http_clients(local)
        sync_client.close()
        async with async_client as client:
            if local:
                result = await client.get(f"{base_url.removesuffix('/v1')}/api/tags", timeout=body.timeout_seconds)
            elif provider_info.api_style == "anthropic":
                result = await client.post(
                    f"{base_url.rstrip('/')}/messages",
                    headers=headers,
                    json={"model": body.model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1},
                    timeout=body.timeout_seconds,
                )
            else:
                result = await client.post(f"{base_url.rstrip('/')}/chat/completions", headers=headers, json={"model": body.model, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 1}, timeout=body.timeout_seconds)
            result.raise_for_status()
        payload = result.json() if not local else {}
        usage = payload.get("usage", {}) if isinstance(payload, dict) else {}
        input_tokens = int(usage.get("prompt_tokens", usage.get("input_tokens", 0)) or 0) if isinstance(usage, dict) else 0
        output_tokens = int(usage.get("completion_tokens", usage.get("output_tokens", 0)) or 0) if isinstance(usage, dict) else 0
        usage_known = local or bool(isinstance(usage, dict) and ("prompt_tokens" in usage or "input_tokens" in usage) and ("completion_tokens" in usage or "output_tokens" in usage))
        usage_service.settle(reservation, request_token, "local" if local else body.provider, body.model, input_tokens, output_tokens, usage_known=usage_known)
        outcome = {"status": "connected", "provider": body.provider, "model": body.model, "latency_ms": round((time.perf_counter() - started) * 1000)}
        operation = _complete(principal, request, operation, result=outcome, reason=body.reason)
        clear_client_cache()
    except AppException as exc:
        if reservation:
            usage_service.settle(reservation, request_token, "local" if local else body.provider, body.model, 0, 0, usage_known=False)
        _complete(principal, request, operation, state="failed", error_code=exc.code, reason=body.reason)
        raise
    except Exception as exc:
        if reservation:
            usage_service.settle(reservation, request_token, "local" if local else body.provider, body.model, 0, 0, usage_known=False)
        _complete(principal, request, operation, state="failed", error_code="LLM_PROBE_FAILED", reason=body.reason)
        raise AppException("LLM_PROBE_FAILED", "模型探测失败", 502, {"reason": type(exc).__name__}) from exc
    _no_store(response)
    return _operation_dict(operation)


@router.get("/security/sessions")
def security_sessions(response: Response, include_revoked: bool = False, limit: int = 50, offset: int = 0, principal: AdminPrincipal = Depends(require_admin)):
    from backend.app.core.admin_security import list_sessions

    result = list_sessions(include_revoked=include_revoked, limit=limit, offset=offset)
    for item in result.get("items", []):
        item["is_current"] = item.get("session_id") == principal.session_id
    _no_store(response)
    return result


@router.get("/security/settings")
def security_settings(response: Response):
    values = get_admin_settings()
    result = {"enabled": values.enabled, "source": "environment_and_database", "allowed_ips_configured": bool(values.allowed_ips), "session_idle_minutes": values.session_idle_minutes, "session_absolute_hours": values.session_absolute_hours, "csrf_token_ttl_minutes": values.csrf_token_ttl_minutes, "max_sessions": values.max_sessions, "secrets": {"csrf_key": "configured"}}
    _no_store(response)
    return result


@router.post("/security/sessions/{session_id}/revoke")
def revoke_security_session(session_id: str, request: Request, response: Response, body: _SessionMutation, idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    _confirm(body.confirm_text, expected=session_id)
    _require_recent_reauth(principal)
    if session_id == principal.session_id:
        raise AppException("ADMIN_CURRENT_SESSION_REVOKE", "当前会话请使用退出登录", 409)
    from backend.app.core.admin_security import revoke_session

    key = _idempotency(idempotency_header, body.idempotency_key)
    operation = _begin(principal, request, kind="session_revoke", scope=session_id, intended={"session_id": session_id}, key=key, reason=body.reason, target_type="admin_session", target_id=session_id, action="SESSION_REVOKE")
    if getattr(operation, "state", None) != "pending":
        _no_store(response)
        return _operation_dict(operation)
    operation = _mark_running(operation)
    try:
        revoked = revoke_session(session_id, actor=principal, request_id=_request_id(request), reason=body.reason)
        operation = _complete(principal, request, operation, result={"session_id": session_id, "revoked": bool(revoked)}, reason=body.reason, action="SESSION_REVOKE")
    except AppException as exc:
        operation = _complete(principal, request, operation, state="failed", error_code=exc.code, reason=body.reason, action="SESSION_REVOKE")
        raise
    result = _operation_dict(operation)
    _no_store(response)
    return result


@router.post("/security/sessions/revoke-all")
def revoke_other_sessions(request: Request, response: Response, body: _SessionMutation, idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    _confirm(body.confirm_text, expected="other_sessions")
    _require_recent_reauth(principal)
    from backend.app.core.admin_security import revoke_all_other_sessions

    key = _idempotency(idempotency_header, body.idempotency_key)
    operation = _begin(principal, request, kind="session_revoke_all", scope="other_sessions", intended={"scope": "other_sessions"}, key=key, reason=body.reason, target_type="admin_sessions", target_id="other_sessions", action="SESSION_REVOKE_ALL")
    if getattr(operation, "state", None) != "pending":
        _no_store(response)
        return _operation_dict(operation)
    operation = _mark_running(operation)
    try:
        count = revoke_all_other_sessions(principal, request_id=_request_id(request), reason=body.reason)
        operation = _complete(principal, request, operation, result={"revoked_count": int(count), "current_session_retained": True}, reason=body.reason, action="SESSION_REVOKE_ALL")
    except AppException as exc:
        operation = _complete(principal, request, operation, state="failed", error_code=exc.code, reason=body.reason, action="SESSION_REVOKE_ALL")
        raise
    result = _operation_dict(operation)
    _no_store(response)
    return result


@router.post("/security/rotate-access-token")
def rotate_access_token(request: Request, response: Response, body: TokenRotateRequest, idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    _confirm(body.confirm_text, expected="API_ACCESS_TOKEN")
    from backend.app.core.admin_security import reauthenticate

    if body.current_password:
        reauthenticate(principal, body.current_password, request_id=_request_id(request))
    _require_recent_reauth(principal)
    key = _idempotency(idempotency_header, body.idempotency_key)
    operation = _begin(principal, request, kind="access_token_rotate", scope="API_ACCESS_TOKEN", intended={"rotated": True}, key=key, reason=body.reason)
    if getattr(operation, "state", None) != "pending":
        _no_store(response)
        return {**_operation_dict(operation), "access_token": None, "requires_reconfiguration": True}
    operation = _mark_running(operation)
    new_token = secrets.token_urlsafe(32)
    try:
        current_settings = get_settings()
        update_settings({"API_ACCESS_TOKEN": new_token}, expected_revision=current_settings.CONFIG_REVISION)
        operation = _complete(principal, request, operation, result={"rotated": True, "requires_reconfiguration": True}, reason=body.reason)
    except Exception as exc:
        _complete(principal, request, operation, state="failed", error_code=getattr(exc, "code", "ACCESS_TOKEN_ROTATE_FAILED"), reason=body.reason)
        raise AppException("ACCESS_TOKEN_ROTATE_FAILED", "访问令牌轮换失败", 503) from exc
    _no_store(response)
    return {**_operation_dict(operation), "access_token": new_token, "requires_reconfiguration": True}


@router.get("/config")
def config_view(response: Response):
    result = _config_view()
    _no_store(response)
    return result


@router.put("/config")
def config_update(request: Request, response: Response, body: ConfigUpdateRequest, idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    _require_recent_reauth(principal)
    key = _idempotency(idempotency_header, body.idempotency_key)
    values = _sanitize_config_values(body.values)
    # The operation digest contains the candidate values as well as keys, but
    # operation sanitization redacts secret-shaped fields before persistence.
    operation = _begin(principal, request, kind="config_update", scope="settings", intended={"keys": sorted(values), "values": values, "expected_revision": body.expected_revision}, key=key, reason=body.reason)
    if getattr(operation, "state", None) != "pending":
        _no_store(response)
        return _operation_dict(operation)
    _mark_running(operation)
    try:
        updated = update_settings(values, expected_revision=body.expected_revision)
        operation = _complete(principal, request, operation, result={"revision": updated.CONFIG_REVISION, "keys": sorted(values)}, reason=body.reason)
    except AppException as exc:
        _complete(principal, request, operation, state="failed", error_code=exc.code, reason=body.reason)
        raise
    except (TypeError, ValueError) as exc:
        _complete(principal, request, operation, state="failed", error_code="CONFIG_INVALID", reason=body.reason)
        raise AppException("CONFIG_INVALID", str(exc), 422) from exc
    _no_store(response)
    return _operation_dict(operation)


@router.get("/audit")
def audit_logs(response: Response, action: str | None = None, actor: str | None = None, result: str | None = None, date_from: str | None = Query(None, alias="from"), date_to: str | None = Query(None, alias="to"), limit: int = 100, offset: int = 0):
    try:
        output = audit.query_audit_logs(action=action, actor=actor, result=result, date_from=date_from, date_to=date_to, limit=limit, offset=offset)
    except ValueError as exc:
        raise AppException("AUDIT_QUERY_INVALID", str(exc), 422) from exc
    _no_store(response)
    return output


@router.post("/operations/{operation_id}/retry")
async def retry_operation(operation_id: str, request: Request, response: Response, body: MutationRequest, idempotency_header: str | None = Header(None, alias="Idempotency-Key"), principal: AdminPrincipal = Depends(require_admin)):
    """Explicitly retry a failed/partial reversible operation.

    The operation service moves the original row back to ``running`` with a
    compare-and-set and increments its attempt count.  A hashed retry key in
    the attempt table makes a repeated network request return the same row
    without replaying the side effect.
    """

    from backend.app.services.admin_operations import get_operation
    from backend.app.services.admin_operations import retry_operation as retry_operation_record

    original = get_operation(operation_id)
    if original.actor_id not in {None, principal.user_id}:
        raise AppException("ADMIN_OPERATION_FORBIDDEN", "无权重试该管理操作", 403)
    if original.state == "succeeded":
        _no_store(response)
        return _operation_dict(original)
    key = _idempotency(idempotency_header, body.idempotency_key)
    if key == original.idempotency_key:
        raise AppException("IDEMPOTENCY_INVALID", "重试必须使用新的Idempotency-Key", 422)
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    db = database.connect()
    try:
        attempt_seen = bool(db.execute("SELECT 1 FROM admin_operation_attempts WHERE operation_id=? AND retry_key_hash=?", (operation_id, digest)).fetchone())
    finally:
        db.close()
    if original.state in {"pending", "running"}:
        if attempt_seen:
            _no_store(response)
            response.status_code = 202
            return _operation_dict(original)
        raise AppException("OPERATION_RUNNING", "操作正在执行，请等待其完成", 409)
    if not original.retryable:
        raise AppException("OPERATION_NOT_RETRYABLE", "该操作当前不可重试", 409)
    intended = dict(original.intended or {})
    kind = original.kind
    supported = {"dataset_delete", "dataset_purge", "discussion_lease_recover", "discussion_force_end", "maintenance", "maintenance_run", "overrun_reset", "budget_limit_update", "ppt_delete", "file_delete", "rag_document_delete", "rag_project_purge"}
    if kind not in supported:
        raise AppException("OPERATION_RETRY_REQUIRES_NEW_REQUEST", "该操作必须重新提交专用请求，不能自动重放", 409)
    _confirm(body.confirm_text, expected=_retry_target_text(original))
    _require_recent_reauth(principal)
    try:
        # retry_operation has a deliberately narrow actor/request contract;
        # network metadata belongs on the audit wrapper, not on the CAS
        # primitive itself.
        retry = retry_operation_record(
            operation_id,
            actor_id=principal.user_id,
            actor_name=principal.username,
            request_id=_request_id(request),
            retry_key=key,
            reason=body.reason,
        )
    except ValueError as exc:
        raise AppException("OPERATION_RETRY_INVALID", str(exc), 422) from exc
    if attempt_seen or retry.state != "running":
        _no_store(response)
        if retry.state == "running":
            response.status_code = 202
        return _operation_dict(retry)
    try:
        if kind == "dataset_delete":
            # Keep the business delete and terminal operation/audit rows in
            # one transaction.  A retry must not erase the target while
            # leaving its original operation in a failed state.
            from backend.app.services.admin_operations import complete_operation_tx

            with database.transaction(immediate=True) as tx:
                result = admin_cleanup.delete_dataset_tx(tx, str(intended["dataset_id"]))
                retry = complete_operation_tx(
                    tx,
                    operation_id,
                    **{
                        **_actor(principal),
                        "request_id": _request_id(request),
                        "result": result,
                        "state": "succeeded",
                        "reason": body.reason,
                    },
                )
            _no_store(response)
            return _operation_dict(retry)
        elif kind == "dataset_purge":
            retry_cutoff = intended.get("cutoff")
            if isinstance(retry_cutoff, str):
                try:
                    retry_cutoff = datetime.fromisoformat(retry_cutoff.replace("Z", "+00:00"))
                    retry_cutoff = retry_cutoff.replace(tzinfo=UTC) if retry_cutoff.tzinfo is None else retry_cutoff.astimezone(UTC)
                except ValueError:
                    retry_cutoff = None
            result = admin_cleanup.purge_expired_datasets(dry_run=bool(intended.get("dry_run", False)), now=retry_cutoff)
        elif kind in {"maintenance", "maintenance_run"}:
            retry_cutoff = intended.get("cutoff")
            if isinstance(retry_cutoff, str):
                retry_cutoff = retry_cutoff.replace("Z", "+00:00")
                try:
                    retry_cutoff = datetime.fromisoformat(retry_cutoff)
                except ValueError:
                    retry_cutoff = None
            result = admin_cleanup.run_cleanup(scopes=intended.get("scope", "all"), dry_run=bool(intended.get("dry_run", False)), now=retry_cutoff)
        elif kind == "overrun_reset":
            result = {"cleared_count": int(usage_service.reset_provider_overrun()), "unknown_holds_retained": True}
        elif kind == "budget_limit_update":
            expected_revision = intended.get("expected_revision")
            value = intended.get("max_budget_usd")
            if expected_revision is None or value is None:
                raise AppException("OPERATION_RETRY_REQUIRES_NEW_REQUEST", "预算上限重试需要重新提交当前配置版本", 409)
            updated = update_settings({"MAX_BUDGET_USD": Decimal(str(value))}, expected_revision=int(expected_revision))
            result = {"revision": int(updated.CONFIG_REVISION), "max_budget_usd": str(updated.MAX_BUDGET_USD)}
        elif kind == "discussion_force_end":
            from backend.app.services.admin_operations import complete_operation_tx
            from backend.app.services.discussion_session import admin_cancel

            session_id = str(intended["session_id"])
            with database.transaction(immediate=True) as tx:
                _assert_session_operation_available(tx, session_id, operation_id)
                result = admin_cancel(tx, session_id)
                retry = complete_operation_tx(tx, operation_id, **{**_actor(principal), "request_id": _request_id(request), "result": result, "state": "succeeded", "reason": body.reason})
            _no_store(response)
            return _operation_dict(retry)
        elif kind == "discussion_lease_recover":
            from backend.app.services.admin_operations import complete_operation
            from backend.app.services.discussion_session import admin_recover, run_admin_recovery

            session_id = str(intended["session_id"])
            with database.transaction(immediate=True) as tx:
                _assert_session_operation_available(tx, session_id, operation_id)
                commands = admin_recover(tx, session_id)

            async def recovery_worker() -> None:
                try:
                    await run_admin_recovery(commands)
                    await asyncio.to_thread(complete_operation, operation_id, **{**_actor(principal), "request_id": _request_id(request), "result": {"session_id": session_id, "queued_commands": len(commands)}, "state": "succeeded", "reason": body.reason})
                except Exception as exc:
                    try:
                        await asyncio.to_thread(complete_operation, operation_id, **{**_actor(principal), "request_id": _request_id(request), "result": {"session_id": session_id}, "state": "failed", "error_code": getattr(exc, "code", type(exc).__name__), "reason": body.reason})
                    except Exception:
                        pass

            _track_background(asyncio.create_task(recovery_worker()))
            _no_store(response)
            response.status_code = 202
            return _operation_dict(retry)
        elif kind in {"ppt_delete", "file_delete"}:
            file_id = str(intended["file_id"])
            db = database.connect()
            try:
                row = db.execute("SELECT file_id,disk_path FROM files WHERE file_id=?", (file_id,)).fetchone()
            finally:
                db.close()
            if not row:
                raise AppException("FILE_NOT_FOUND", "文件登记不存在", 404)
            path = Path(str(row["disk_path"])).resolve()
            output = Path(ppt_service.OUTPUT_DIR).resolve()
            if os.path.commonpath([str(path), str(output)]) != str(output):
                raise AppException("FILE_PATH_INVALID", "文件路径不在成果目录内", 400)
            if not path.is_file():
                result = {"file_id": file_id, "status": "partial", "deleted": False, "integrity_status": "missing"}
                retry = _complete(principal, request, retry, result=result, state="partial", error_code="FILE_MISSING", reason=body.reason, action="PPT_DELETE")
                _no_store(response)
                return _operation_dict(retry)
            path.unlink()
            with database.transaction(immediate=True) as db:
                db.execute("DELETE FROM files WHERE file_id=?", (file_id,))
            result = {"file_id": file_id, "deleted": True}
        elif kind in {"rag_document_delete", "rag_project_purge"}:
            project_id = str(intended["project_id"])
            async def rag_worker() -> tuple[dict[str, Any] | None, Exception | None, Any | None]:
                try:
                    result = await rag_service_module.rag_service.admin_delete(project_id, intended.get("document_id") if kind == "rag_document_delete" else None)
                    result = result or {}
                    prior = original.result if isinstance(original.result, dict) else {}
                    if "deleted_chunks" in result:
                        result["deleted_chunks"] = int(prior.get("deleted_chunks", 0) or 0) + int(result.get("deleted_chunks", 0) or 0)
                    if "failed_collections" in result:
                        current_failed = result.get("failed_collections", []) if isinstance(result.get("failed_collections", []), list) else []
                        # The field describes failures that remain after this
                        # attempt.  Successful prior chunks are cumulative,
                        # while a collection that succeeds on retry must no
                        # longer be reported as failed.
                        result["failed_collections"] = list(dict.fromkeys(current_failed))
                    state = "partial" if result.get("status") == "partial" else "succeeded"
                    completed = await asyncio.to_thread(_complete, principal, request, retry, result=result, state=state, error_code="RAG_PARTIAL" if state == "partial" else None, reason=body.reason)
                    return result, None, completed
                except Exception as exc:
                    try:
                        await asyncio.to_thread(_complete, principal, request, retry, state="failed", error_code=getattr(exc, "code", "RAG_RETRY_FAILED"), reason=body.reason)
                    except Exception:
                        pass
                    return None, exc, None

            rag_task = _track_background(asyncio.create_task(rag_worker()))
            try:
                result, rag_error, completed = await asyncio.wait_for(asyncio.shield(rag_task), timeout=3.0)
            except asyncio.TimeoutError:
                _no_store(response)
                response.status_code = 202
                return _operation_dict(retry)
            if rag_error is not None:
                raise rag_error
            result = result or {}
            retry = completed or retry
        else:  # pragma: no cover - protected by supported set
            raise AppException("OPERATION_RETRY_REQUIRES_NEW_REQUEST", "该操作必须重新提交专用请求", 409)
        partial = False
        if isinstance(result, dict):
            partial = result.get("status") == "partial"
            if isinstance(result.get("scopes"), dict):
                partial = partial or any(
                    int(item.get("failed", 0) or 0) > 0 or int(item.get("unknown", 0) or 0) > 0
                    for item in result["scopes"].values()
                    if isinstance(item, dict)
                )
        state = "partial" if partial else "succeeded"
        partial_code = {
            "dataset_purge": "DATASET_PURGE_PARTIAL",
            "maintenance": "MAINTENANCE_PARTIAL",
            "maintenance_run": "MAINTENANCE_PARTIAL",
            "rag_document_delete": "RAG_PARTIAL",
            "rag_project_purge": "RAG_PARTIAL",
        }.get(kind, "OPERATION_PARTIAL")
        retry = _complete(
            principal,
            request,
            retry,
            result=result if isinstance(result, dict) else {"result": result},
            state=state,
            error_code=partial_code if partial else None,
            reason=body.reason,
        )
    except AppException as exc:
        retry = _complete(principal, request, retry, state="failed", error_code=exc.code, reason=body.reason)
        raise
    except Exception as exc:
        retry = _complete(principal, request, retry, state="failed", error_code=f"{kind.upper()}_RETRY_FAILED", reason=body.reason)
        raise AppException("OPERATION_RETRY_FAILED", "管理操作重试失败，请查询操作详情", 503) from exc
    _no_store(response)
    return _operation_dict(retry)


def _operation_lookup(operation_id: str, principal: AdminPrincipal) -> dict[str, Any]:
    try:
        from backend.app.services.admin_operations import get_operation

        operation = get_operation(operation_id)
    except AppException:
        raise
    except Exception as exc:
        raise AppException("ADMIN_OPERATIONS_UNAVAILABLE", "管理操作服务暂时不可用", 503) from exc
    if operation.actor_id not in {None, principal.user_id}:
        raise AppException("ADMIN_OPERATION_FORBIDDEN", "无权查看该管理操作", 403)
    return _operation_dict(operation)


@router.get("/operations/{operation_id}")
def operation(operation_id: str, response: Response, principal: AdminPrincipal = Depends(require_admin)):
    result = _operation_lookup(operation_id, principal)
    _no_store(response)
    return result


@router.get("/operations")
def operations(response: Response, key: str | None = None, state: str | None = None, limit: int = 50, offset: int = 0, principal: AdminPrincipal = Depends(require_admin)):
    try:
        from backend.app.services.admin_operations import list_operations

        result = list_operations(actor_id=principal.user_id, idempotency_key=key, state=state, limit=limit, offset=offset)
    except ValueError as exc:
        raise AppException("OPERATION_QUERY_INVALID", str(exc), 422) from exc
    result["items"] = [_operation_dict(item) for item in result.get("items", [])]
    _no_store(response)
    return result


def recover_interrupted_admin_operations() -> dict[str, int]:
    """Mark intents left by a crashed process as explicitly retryable.

    This hook is safe to call from application startup. It never replays a
    side effect (especially a credential or token action); callers must use
    the retry endpoint after reviewing the failed intent.
    """

    from backend.app.services.admin_operations import complete_operation_tx

    interrupted = 0
    with database.transaction(immediate=True) as db:
        rows = db.execute("SELECT operation_id,kind,scope FROM admin_operations WHERE state IN ('pending','running') ORDER BY created_at,operation_id").fetchall()
        for row in rows:
            complete_operation_tx(
                db,
                row["operation_id"],
                actor_id="system",
                actor_name="system",
                request_id=f"admin_startup_recovery_{row['operation_id']}",
                result={"interrupted": True, "kind": str(row["kind"]), "scope": str(row["scope"])},
                state="failed",
                error_code="ADMIN_WORKER_INTERRUPTED",
                reason="进程重启后管理操作未完成，请人工确认后重试",
            )
            interrupted += 1
    return {"interrupted": interrupted}


async def startup_admin_recovery() -> dict[str, int]:
    return await asyncio.to_thread(recover_interrupted_admin_operations)


async def shutdown_admin_recovery_workers() -> None:
    tasks = tuple(_BACKGROUND_TASKS)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


__all__ = ["router", "recover_interrupted_admin_operations", "startup_admin_recovery", "shutdown_admin_recovery_workers"]
