from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
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
_ws_limiter = SlidingWindowRateLimiter(120)


def rebuild_rate_limiter() -> None:
    global _limiter, _ws_limiter
    _limiter = SlidingWindowRateLimiter(get_settings().RATE_LIMIT_PER_MINUTE)
    _ws_limiter = SlidingWindowRateLimiter(get_settings().RATE_LIMIT_PER_MINUTE)


async def check_websocket_rate_limit(websocket: WebSocket) -> bool:
    if await _ws_limiter.check(websocket.client.host if websocket.client else "unknown"):
        return True
    await websocket.close(code=4429)
    return False


EXEMPT_PATHS = {"/", "/api/health"}


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in EXEMPT_PATHS or request.url.path == "/api/admin" or request.url.path.startswith("/api/admin/") or request.method == "OPTIONS":
            return await call_next(request)
        allowed = await _limiter.check(_client_ip(request))
        if not allowed:
            logger.warning("rate limit exceeded for %s on %s", _client_ip(request), request.url.path)
            return JSONResponse(status_code=429, content={"code": "RATE_LIMITED", "message": "请求过于频繁，请稍后再试"}, headers={"Retry-After": "60"})
        return await call_next(request)


def _client_ip(request: Request) -> str:
    # Forwarded headers must be resolved by a correctly configured trusted proxy
    # (e.g. uvicorn --forwarded-allow-ips), never by arbitrary request headers.
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
    try:
        parts = urlsplit(raw_url.strip())
        port = parts.port
    except ValueError as exc:
        raise AppException("MODEL_BASE_URL_INVALID", "API 地址格式或端口无效", 400) from exc
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise AppException("MODEL_BASE_URL_INVALID", "API 地址必须是以 http(s):// 开头的合法 URL", 400)
    if parts.username or parts.password or "@" in raw_url.split("?", 1)[0].split("//", 1)[-1]:
        raise AppException("MODEL_BASE_URL_INVALID", "API 地址不允许携带凭据信息", 400)
    hostname = parts.hostname.lower()
    if parts.query or parts.fragment:
        raise AppException("MODEL_BASE_URL_INVALID", "API 地址不允许查询参数或片段", 400)
    if not allow_private and (hostname in _BLOCKED_HOSTS or _is_private_host(hostname)):
        raise AppException("MODEL_BASE_URL_INVALID", "外部模型服务不允许指向内网地址；如需本地服务请开启“使用本地模型”", 400)
    if not allow_private:
        resolve_public_addresses(hostname, port or (443 if parts.scheme == "https" else 80))
    return raw_url.strip().rstrip("/")


def resolve_public_addresses(host: str, port: int) -> list[str]:
    try:
        addresses = list(dict.fromkeys(row[4][0] for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
        if not addresses or any(not ipaddress.ip_address(address).is_global for address in addresses):
            raise ValueError("non-public address")
        return addresses
    except (OSError, ValueError) as exc:
        raise AppException("MODEL_BASE_URL_INVALID", "外部模型地址未解析为有效公网地址", 400) from exc


def outbound_http_clients(allow_private: bool = False):
    """Pin each TCP connection to a checked address; TLS still uses original SNI.

    No ambient proxy or redirects: neither may silently redirect credentials.
    DNS is checked at connection time, so rebinding after config validation fails.
    """
    import httpx
    from httpcore._backends.auto import AutoBackend
    from httpcore._backends.sync import SyncBackend

    class CheckedSyncBackend(SyncBackend):
        def connect_tcp(self, host, port, **kwargs):
            address = host if allow_private else resolve_public_addresses(host, port)[0]
            return super().connect_tcp(address, port, **kwargs)

    class CheckedAsyncBackend(AutoBackend):
        async def connect_tcp(self, host, port, **kwargs):
            address = host if allow_private else (await asyncio.to_thread(resolve_public_addresses, host, port))[0]
            return await super().connect_tcp(address, port, **kwargs)

    sync_transport = httpx.HTTPTransport(retries=0)
    async_transport = httpx.AsyncHTTPTransport(retries=0)
    sync_transport._pool._network_backend = CheckedSyncBackend()
    async_transport._pool._network_backend = CheckedAsyncBackend()
    return (httpx.Client(transport=sync_transport, trust_env=False, follow_redirects=False),
            httpx.AsyncClient(transport=async_transport, trust_env=False, follow_redirects=False))
