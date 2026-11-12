from __future__ import annotations

import re
from typing import Any, Mapping

_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[a-z0-9._\-]+"),
    re.compile(r"(?i)(access_token=)[^&\s]+"),
    re.compile(r"(?i)sk-[a-z0-9\-]+"),
    re.compile(r"(?i)(api[_-]?key[\"']?\s*[:=]\s*[\"']?)[^\"'\s]+"),
    re.compile(r"EAA[A-Za-z0-9]+"),
)

_SECRET_KEYS = frozenset(
    {
        "authorization",
        "access_token",
        "page_access_token",
        "api_key",
        "apikey",
        "llm_api_key",
        "meta_page_access_token",
        "token",
        "secret",
        "password",
    }
)


def redact_text(value: str) -> str:
    out = value
    for pat in _PATTERNS:
        out = pat.sub(lambda m: (m.group(1) if m.lastindex else "") + "[REDACTED]", out)
    return out


def redact(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Mapping):
        cleaned = {}
        for k, v in value.items():
            if str(k).lower() in _SECRET_KEYS:
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = redact(v)
        return cleaned
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value
