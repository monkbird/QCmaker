import pytest
from starlette.requests import Request

from backend.app.core import admin_security as security


def request(*, host='localhost:5173', origin='http://localhost:5173', scheme='http', forwarded=None, client='127.0.0.1'):
    headers = [(b'host', host.encode()), (b'origin', origin.encode())]
    if forwarded:
        headers.extend([(b'x-forwarded-host', forwarded.encode()), (b'x-forwarded-proto', b'http')])
    return Request({'type': 'http', 'method': 'POST', 'scheme': scheme, 'path': '/api/admin/auth/login',
                    'query_string': b'', 'headers': headers, 'server': (host, 80), 'client': (client, 1234)})


def test_forwarded_headers_cannot_authorize_foreign_origin(monkeypatch):
    monkeypatch.setenv('ENVIRONMENT', 'development')
    with pytest.raises(security.AdminSecurityError):
        security.require_same_origin(request(origin='http://attacker.invalid', forwarded='attacker.invalid'))


def test_same_origin_https_works_without_business_cors_entry(monkeypatch):
    monkeypatch.setenv('ENVIRONMENT', 'production')
    security.require_same_origin(request(host='admin.example', origin='https://admin.example', scheme='https'))


def test_development_cookie_exception_does_not_accept_fake_loopback_host(monkeypatch):
    monkeypatch.setenv('ENVIRONMENT', 'development')
    with pytest.raises(security.AdminSecurityError):
        security.cookie_secure(request(host='127.evil.invalid', origin='http://127.evil.invalid', client='8.8.8.8'))
