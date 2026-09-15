from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class AppException(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400, details: dict[str, Any] | None = None):
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details
        super().__init__(message)


def error_payload(request: Request, code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"code": code, "message": message, "details": details, "request_id": getattr(request.state, "request_id", None)}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppException)
    async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
        if request.url.path.startswith('/api/admin/'):
            from backend.app.services.admin_redaction import redact_admin_text
            from backend.app.services.audit import sanitize_summary
            return JSONResponse(content=error_payload(request, exc.code, redact_admin_text(exc.message), sanitize_summary(exc.details)), status_code=exc.status_code, headers={'Cache-Control': 'no-store'})
        return JSONResponse(content=error_payload(request, exc.code, exc.message, exc.details), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        if request.url.path.startswith('/api/admin/'):
            # Pydantic's input/ctx can contain passwords or whole request bodies.
            errors = [{"loc": list(item['loc']), "type": item['type']} for item in exc.errors()]
            return JSONResponse(content=error_payload(request, "REQUEST_INVALID", "请求参数不合法", {"errors": errors}), status_code=422)
        return JSONResponse(content=error_payload(request, "REQUEST_INVALID", "请求参数不合法", {"errors": jsonable_encoder(exc.errors(), custom_encoder={ValueError: str})}), status_code=422)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception) -> JSONResponse:
        logging.getLogger(__name__).exception("Unhandled request error", exc_info=exc)
        return JSONResponse(content=error_payload(request, "INTERNAL_ERROR", "服务内部错误"), status_code=500)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        supplied = request.headers.get("x-request-id", "")
        request.state.request_id = supplied if 1 <= len(supplied) <= 100 and all(c.isascii() and (c.isalnum() or c in '-_.') for c in supplied) else f"req_{uuid4().hex}"
        response = await call_next(request)
        response.headers["x-request-id"] = request.state.request_id
        if request.url.path == '/api/admin' or request.url.path.startswith('/api/admin/'):
            response.headers['Cache-Control'] = 'no-store'
        return response
