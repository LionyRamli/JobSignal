"""Shared domain models passed between extraction, harmonization, storage and signals."""

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator


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
