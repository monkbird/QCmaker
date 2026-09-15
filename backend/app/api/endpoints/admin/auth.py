"""Cookie-session authentication endpoints for the management console."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from backend.app.core.admin_security import (
    SESSION_COOKIE_NAME,
    AdminPrincipal,
    AdminRateLimitError,
    AdminSecurityError,
    authenticate,
    change_password,
    client_ip,
    cookie_attributes,
    ensure_admin_ready,
    get_me,
    logout_session,
    reauthenticate,
    require_admin,
    require_json_content_type,
    require_same_origin,
    touch_activity,
    validate_session,
)
from backend.app.core.errors import error_payload
from backend.app.models.admin_contracts import (
    AdminActivityRequest,
    AdminChangePasswordRequest,
    AdminChangePasswordResponse,
    AdminLoginRequest,
    AdminLogoutResponse,
    AdminMeResponse,
    AdminReauthRequest,
    AdminReauthResponse,
    AdminSessionView,
    AdminUserView,
)

router = APIRouter(prefix="/auth", tags=["admin-auth"])


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", None) or request.headers.get("x-request-id") or "admin_req_unknown"


def _session_view(principal: AdminPrincipal) -> AdminSessionView:
    return AdminSessionView(
        session_id=principal.session_id,
        user_id=principal.user_id,
        ip=principal.ip,
        user_agent_hash=principal.user_agent_hash,
        created_at=principal.created_at,
        last_activity_at=principal.last_activity_at,
        last_request_at=principal.last_request_at,
        idle_expires_at=principal.idle_expires_at,
        absolute_expires_at=principal.absolute_expires_at,
        is_current=True,
    )


def _response(principal: AdminPrincipal) -> AdminMeResponse:
    return AdminMeResponse(
        user=AdminUserView(user_id=principal.user_id, username=principal.username, is_active=principal.is_active),
        session=_session_view(principal),
        csrf_token=principal.csrf_token,
        server_time=datetime.now(UTC),
        idle_expires_at=principal.idle_expires_at,
        absolute_expires_at=principal.absolute_expires_at,
    )


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"


def _set_session_cookie(response: Response, request: Request, principal: AdminPrincipal) -> None:
    # Raw SID is deliberately only placed in the HttpOnly cookie.  It is not
    # part of the Pydantic response contract.
    response.set_cookie(SESSION_COOKIE_NAME, principal.session_secret, **cookie_attributes(request))


def _clear_session_cookie(response: Response, request: Request) -> None:
    attrs = cookie_attributes(request)
    response.delete_cookie(SESSION_COOKIE_NAME, path=attrs["path"], secure=attrs["secure"], httponly=attrs["httponly"], samesite=attrs["samesite"])


def _rate_limit_response(request: Request, exc: AdminRateLimitError) -> JSONResponse:
    response = JSONResponse(content=error_payload(request, exc.code, exc.message, exc.details), status_code=429, headers={"Retry-After": str(exc.retry_after)})
    _no_store(response)
    return response


@router.post("/login", response_model=AdminMeResponse)
async def login(request: Request, response: Response):
    ensure_admin_ready()
    require_json_content_type(request)
    require_same_origin(request)
    try:
        payload = AdminLoginRequest.model_validate(await request.json())
    except (ValidationError, ValueError, TypeError) as exc:
        raise AdminSecurityError("ADMIN_LOGIN_FAILED", "用户名或密码错误", 401) from exc
    try:
        principal = authenticate(
            payload.username,
            payload.password,
            source_ip=client_ip(request),
            user_agent=request.headers.get("user-agent"),
            request_id=_request_id(request),
        )
    except AdminRateLimitError as exc:
        return _rate_limit_response(request, exc)
    _set_session_cookie(response, request, principal)
    _no_store(response)
    return _response(principal)


@router.get("/me", response_model=AdminMeResponse)
def me(request: Request, response: Response, principal: AdminPrincipal = Depends(require_admin)):
    current = get_me(principal)
    _no_store(response)
    return _response(current)


@router.post("/activity", response_model=AdminMeResponse)
def activity(request: Request, response: Response, _: AdminActivityRequest | None = None, principal: AdminPrincipal = Depends(require_admin)):
    current = touch_activity(principal)
    _no_store(response)
    return _response(current)


@router.post("/logout", response_model=AdminLogoutResponse)
def logout(request: Request, response: Response):
    """Revoke the current session; expired/repeated logout is idempotent."""

    raw_secret = None
    try:
        from backend.app.core.admin_security import _extract_cookie

        raw_secret = _extract_cookie(request)
    except AdminSecurityError:
        raw_secret = None
    if raw_secret:
        try:
            principal = validate_session(raw_secret, request=request)
            from backend.app.core.admin_security import validate_csrf

            validate_csrf(request, principal)
            logout_session(principal, request_id=_request_id(request))
        except AdminSecurityError as exc:
            # A session that is already expired/revoked has no authority to
            # perform another state change, but logout still clears the
            # browser cookie and returns a stable success shape.
            if exc.code not in {"ADMIN_SESSION_EXPIRED", "ADMIN_SESSION_INVALID"}:
                raise
    try:
        _clear_session_cookie(response, request)
    except AdminSecurityError:
        # In an invalid non-HTTPS deployment, there is no secure cookie to
        # clear.  Keep logout idempotent while preserving the same response.
        response.delete_cookie(SESSION_COOKIE_NAME, path="/api/admin")
    _no_store(response)
    return AdminLogoutResponse(revoked=True)


@router.post("/change-password", response_model=AdminChangePasswordResponse)
def change_password_endpoint(request: Request, response: Response, payload: AdminChangePasswordRequest, principal: AdminPrincipal = Depends(require_admin)):
    result = change_password(principal, payload.old_password, payload.new_password, reason=payload.reason, request_id=_request_id(request))
    _clear_session_cookie(response, request)
    _no_store(response)
    return AdminChangePasswordResponse(relogin_required=result.relogin_required)


@router.post("/reauth", response_model=AdminReauthResponse)
def reauth(request: Request, response: Response, payload: AdminReauthRequest, principal: AdminPrincipal = Depends(require_admin)):
    try:
        timestamp = reauthenticate(principal, payload.current_password, request_id=_request_id(request))
    except AdminRateLimitError as exc:
        return _rate_limit_response(request, exc)
    _no_store(response)
    return AdminReauthResponse(reauthenticated=True, reauthenticated_at=timestamp)


__all__ = ["router"]
