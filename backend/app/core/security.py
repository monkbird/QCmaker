from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlsplit

from fastapi import Request, WebSocket
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from backend.app.core.config import get_settings
from backend.app.core.errors import AppException

logger = logging.getLogger(__name__)

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for header, value in _SECURITY_HEADERS.items(): response.headers.setdefault(header, value)
        return response


class RateLimitExceeded(Exception):
    pass


class SlidingWindowRateLimiter:
    """Per-IP sliding window limiter; single-process only (fits the SQLite deployment model)."""

    def __init__(self, limit_per_minute: int):
        self.limit = max(0, int(limit_per_minute)); self._events: dict[str, list[float]] = {}; self._lock = asyncio.Lock()

    async def check(self, client_key: str) -> bool:
        if self.limit <= 0: return True
        now = time.monotonic()
        async with self._lock:
            window = [stamp for stamp in self._events.get(client_key, []) if now - stamp < 60.0]
            if len(window) >= self.limit:
                self._events[client_key] = window
                return False
            window.append(now); self._events[client_key] = window
            if len(self._events) > 10_000:
                for key in [k for k, v in self._events.items() if not v or now - v[-1] >= 60.0][:5_000]: self._events.pop(key, None)
            return True


_limiter = SlidingWindowRateLimiter(120)


def rebuild_rate_limiter() -> None:
    global _limiter
    _limiter = SlidingWindowRateLimiter(get_settings().RATE_LIMIT_PER_MINUTE)


EXEMPT_PATHS = {"/", "/api/health"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS or request.method == "OPTIONS":
            return await call_next(request)
        allowed = await _limiter.check(_client_ip(request))
        if not allowed:
            logger.warning("rate limit exceeded for %s on %s", _client_ip(request), request.url.path)
            return JSONResponse(status_code=429, content={"code": "RATE_LIMITED", "message": "请求过于频繁，请稍后再试"}, headers={"Retry-After": "60"})
        return await call_next(request)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded: return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def verify_access_token(request: Request) -> None:
    token = get_settings().API_ACCESS_TOKEN
    if not token: return
    supplied = request.headers.get("x-api-token") or request.query_params.get("token")
    if supplied != token: raise AppException("UNAUTHORIZED", "缺少或错误的访问令牌", 401)


async def verify_websocket_token(websocket: WebSocket) -> bool:
    token = get_settings().API_ACCESS_TOKEN
    if not token: return True
    supplied = websocket.headers.get("x-api-token") or websocket.query_params.get("token")
    if supplied != token:
        await websocket.close(code=4401)
        return False
    return True


_BLOCKED_HOSTS = {"metadata.google.internal", "169.254.169.254"}


def _is_private_host(hostname: str) -> bool:
    if hostname in {"localhost"} or hostname.endswith((".local", ".internal")): return True
    try:
        import ipaddress
        return not ipaddress.ip_address(hostname).is_global
    except ValueError:
        return False


def validate_outbound_base_url(raw_url: str, allow_private: bool = False) -> str:
    """SSRF guard for user-supplied LLM endpoints: scheme + credential checks, optional private-host block."""
    parts = urlsplit(raw_url.strip())
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise AppException("MODEL_BASE_URL_INVALID", "API 地址必须是以 http(s):// 开头的合法 URL", 400)
    if parts.username or parts.password or "@" in raw_url.split("?", 1)[0].split("//", 1)[-1]:
        raise AppException("MODEL_BASE_URL_INVALID", "API 地址不允许携带凭据信息", 400)
    hostname = parts.hostname.lower()
    if not allow_private and (hostname in _BLOCKED_HOSTS or _is_private_host(hostname)):
        raise AppException("MODEL_BASE_URL_INVALID", "外部模型服务不允许指向内网地址；如需本地服务请开启“使用本地模型”", 400)
    return raw_url.strip().rstrip("/")
