"""Typed client for the read-only JobSignal API (the dashboard's only data source).

Responses are parsed into the API's own response models (jobsignal.api.schemas), so a
contract drift fails loudly here instead of rendering half-empty tables. Failures become
ApiError subclasses whose message is safe to show to a client: never a traceback, a
response body or the API key.
"""

from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import TypeAdapter, ValidationError

from jobsignal.api.schemas import (
    Company,
    CompanyTrend,
    CompositionOut,
    Health,
    Meta,
    PostingsPage,
    SignalDetail,
    SignalRunOut,
    SignalsPage,
    SignalTrend,
)
from jobsignal.config import Settings, get_settings

TIMEOUT_SECONDS = 10.0
MAX_TREND_IDS = 50  # the API's per-call limit


class ApiError(Exception):
    """An API failure; ``str()`` is the user-facing message."""


class ApiUnavailable(ApiError):  # noqa: N818 - plan's interface names
    pass


class ApiAuthError(ApiError):
    pass


class ApiSchemaMissing(ApiError):  # noqa: N818 - plan's interface names
    pass


class ApiNotFound(ApiError):  # noqa: N818 - plan's interface names
    pass


AUTH_MESSAGE = "The API rejected the request: set JOBSIGNAL_API_KEY to the API's key."


def _detail(response: httpx.Response) -> str | None:
    try:
        detail = response.json().get("detail")
    except (ValueError, AttributeError):
        return None
    return detail if isinstance(detail, str) else None


class ApiClient:
    def __init__(self, http: httpx.Client) -> None:
        self._http = http

    @property
    def base_url(self) -> str:
        return str(self._http.base_url).rstrip("/")

    def _get(self, path: str, params: dict[str, Any] | None = None, *, ok_503: bool = False):
        query = {k: v for k, v in (params or {}).items() if v is not None}
        try:
            response = self._http.get(f"/api/v1{path}", params=query)
        except httpx.TransportError:
            raise ApiUnavailable(
                f"Cannot reach the JobSignal API at {self.base_url}. "
                "Start it with: uv run python scripts/run_api.py"
            ) from None
        status = response.status_code
        unexpected = ApiError(f"Unexpected response from the API (HTTP {status}).")
        if status == 401:
            raise ApiAuthError(AUTH_MESSAGE)
        if status == 503 and not ok_503:
            raise ApiSchemaMissing(_detail(response) or str(unexpected))
        if status == 404:
            raise ApiNotFound(_detail(response) or str(unexpected))
        if status >= 400 and not (status == 503 and ok_503):
            raise unexpected
        try:
            return response.json()
        except ValueError:
            raise unexpected from None

    def _parse(self, model, data):
        try:
            return TypeAdapter(model).validate_python(data)
        except ValidationError:
            raise ApiError("Unexpected response from the API (HTTP 200).") from None

    def health(self) -> Health:
        """API status; a missing schema is reported (503 body), not raised."""
        return self._parse(Health, self._get("/health", ok_503=True))

    def meta(self) -> Meta:
        return self._parse(Meta, self._get("/meta"))

    def companies(self) -> list[Company]:
        return self._parse(list[Company], self._get("/companies"))

    def composition(self, board_token: str) -> CompositionOut:
        return self._parse(CompositionOut, self._get(f"/companies/{board_token}/composition"))

    def company_trends(self, weeks: int = 12) -> list[CompanyTrend]:
        return self._parse(list[CompanyTrend], self._get("/company-trends", {"weeks": weeks}))

    def signal_runs(self, limit: int = 50) -> list[SignalRunOut]:
        return self._parse(list[SignalRunOut], self._get("/signal-runs", {"limit": limit}))

    def signals(
        self,
        run: str | int = "latest",
        *,
        detector: str | None = None,
        direction: str | None = None,
        level: str | None = None,
        company: str | None = None,
        min_abs_z: float | None = None,
        signals_only: bool = True,
        limit: int = 500,
    ) -> SignalsPage:
        params = {
            "run": str(run),
            "detector": detector,
            "direction": direction,
            "level": level,
            "company": company,
            "min_abs_z": min_abs_z,
            "signals_only": str(signals_only).lower(),
            "limit": limit,
        }
        return self._parse(SignalsPage, self._get("/signals", params))

    def signal(self, signal_id: int) -> SignalDetail:
        return self._parse(SignalDetail, self._get(f"/signals/{int(signal_id)}"))

    def signal_trends(self, ids: Sequence[int]) -> list[SignalTrend]:
        """Trends for many scores; no request for no ids; chunked to the API's limit."""
        wanted = list(dict.fromkeys(int(i) for i in ids))
        result: list[SignalTrend] = []
        for start in range(0, len(wanted), MAX_TREND_IDS):
            chunk = wanted[start : start + MAX_TREND_IDS]
            data = self._get("/signals/trends", {"ids": chunk})
            result += self._parse(list[SignalTrend], data)
        return result

    def postings_page(
        self,
        *,
        company: str | None = None,
        role_family: str | None = None,
        seniority: str | None = None,
        country: str | None = None,
        open: bool = True,  # mirrors the API's query parameter
        limit: int = 200,
        cursor: str | None = None,
    ) -> PostingsPage:
        """ONE page of postings (never follows next_cursor: the UI loads more on demand)."""
        params = {
            "company": company,
            "role_family": role_family,
            "seniority": seniority,
            "country": country,
            "open": str(open).lower(),
            "limit": limit,
            "cursor": cursor,
        }
        return self._parse(PostingsPage, self._get("/postings", params))


def make_client(settings: Settings | None = None) -> ApiClient:
    """A client for the configured API; the key travels only in the X-API-Key header."""
    settings = settings or get_settings()
    headers = {}
    if settings.api_key is not None:
        headers["X-API-Key"] = settings.api_key.get_secret_value()
    return ApiClient(
        httpx.Client(base_url=settings.api_url, headers=headers, timeout=TIMEOUT_SECONDS)
    )
