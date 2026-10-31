"""Optional API-key protection (mandatory when serving beyond localhost)."""

import hmac
from collections.abc import Callable

from fastapi import HTTPException, Request
from pydantic import SecretStr

INVALID_KEY = "invalid or missing API key"


def api_key_dependency(key: SecretStr | None) -> Callable[[Request], None]:
    """A FastAPI dependency: no-op without a key, constant-time X-API-Key check with one."""
    expected = key.get_secret_value().encode("utf-8") if key is not None else None

    def check(request: Request) -> None:
        if expected is None:
            return
        given = request.headers.get("X-API-Key", "").encode("utf-8")
        if not hmac.compare_digest(given, expected):
            raise HTTPException(status_code=401, detail=INVALID_KEY)

    return check
