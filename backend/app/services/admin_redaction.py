"""Shared outbound redaction for management text, including known credentials."""
from __future__ import annotations

import json
import re
from urllib.parse import quote

from backend.app.core.config import get_settings
from backend.app.middleware.pii import pii_redactor

_ASSIGNMENT = re.compile(r'''(?ix)(?:authorization|cookie|set-cookie|password|passwd|secret|token|api[_-]?key|access[_-]?token)["']?\s*[:=]\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;&]+)''')
_BEARER = re.compile(r'(?i)\bBearer\s+[^\s,;]+|\bsk-[a-z0-9_-]{8,}')
_URL_CREDENTIAL = re.compile(r'(https?://)[^\s/@]+:[^\s/@]+@', re.I)
_PRIVATE_PATH = re.compile(r'''(?i)\b[a-z]:[\\/][^\s"'<>]+|/(?:home|Users|etc|var|tmp)/[^\s"'<>]+''')


def redact_admin_text(value: object, *, max_length: int = 2000) -> str:
    text = str(value) if value is not None else ''
    settings = get_settings()
    secrets = [settings.OPENAI_API_KEY, settings.TAVILY_API_KEY, settings.API_ACCESS_TOKEN]
    try:
        credentials = json.loads(settings.PROVIDER_CREDENTIALS or '{}')
        if isinstance(credentials, dict):
            secrets.extend(item.get('api_key') for item in credentials.values() if isinstance(item, dict))
    except (ValueError, TypeError):
        pass
    variants = set()
    for secret in secrets:
        if isinstance(secret, str) and secret:
            variants.update((secret, quote(secret, safe=''), json.dumps(secret, ensure_ascii=False)[1:-1]))
    for secret in sorted(variants, key=len, reverse=True):
        text = text.replace(secret, '[REDACTED]')
    text = _URL_CREDENTIAL.sub(r'\1[REDACTED]@', text)
    text = _BEARER.sub('[REDACTED]', text)
    text = _ASSIGNMENT.sub('[REDACTED]', text)
    text = _PRIVATE_PATH.sub('[PATH]', text)
    text = pii_redactor.redact(text).replace('\x00', '')
    return text[:max_length]
