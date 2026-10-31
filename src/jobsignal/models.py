"""Shared domain models passed between extraction, harmonization, storage and signals."""

from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator

# Storage column sizes (storage/schema.py reads these). PostgreSQL enforces VARCHAR(n),
# SQLite does not, so limits are applied here, before data reaches any database.
TITLE_MAX = 512
DEPARTMENT_MAX = 256
EXTERNAL_ID_MAX = 64


class Posting(BaseModel):
    """One open job posting as seen on an ATS board at ``fetched_at``."""

    model_config = ConfigDict(frozen=True)

    source: str
    company: str
    external_id: str
    title: str
    location_raw: str | None
    department: str | None
    url: str
    first_published: AwareDatetime | None
    updated_at: AwareDatetime | None
    fetched_at: AwareDatetime

    @field_validator("title", "external_id")
    @classmethod
    def _strip_required(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("external_id")
    @classmethod
    def _bounded_identity(cls, value: str) -> str:
        if len(value) > EXTERNAL_ID_MAX:  # identity: truncating could merge two postings
            raise ValueError(f"external_id longer than {EXTERNAL_ID_MAX} characters")
        return value

    @field_validator("title")
    @classmethod
    def _truncate_title(cls, value: str) -> str:
        return value[:TITLE_MAX]

    @field_validator("department")
    @classmethod
    def _truncate_department(cls, value: str | None) -> str | None:
        return None if value is None else value[:DEPARTMENT_MAX]

    @field_validator("url")
    @classmethod
    def _require_http_url(cls, value: str) -> str:
        # Untrusted ATS data ends up as dashboard links: block javascript:/data: etc.
        parts = urlsplit(value.strip())
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("url must be an absolute http(s) URL")
        return value.strip()
