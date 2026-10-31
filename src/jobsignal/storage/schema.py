"""SQLAlchemy ORM schema. Alembic autogenerates migrations from this module.

History model: every scrape run has one snapshot per company; ``snapshot_postings`` records
exactly which postings were open in each snapshot, and ``postings`` carries
first_seen/last_seen/closed_at for posting-duration analysis (Phase 2).
"""

from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    Column,
    ForeignKey,
    Index,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from jobsignal.models import DEPARTMENT_MAX, EXTERNAL_ID_MAX, TITLE_MAX
from jobsignal.storage.types import UTCDateTime

# Deterministic constraint names so migrations work identically on SQLite and PostgreSQL.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

RUN_STATUSES = ("running", "succeeded", "partial", "failed")
SNAPSHOT_STATUSES = ("ok", "partial", "failed")
LOCATION_KINDS = ("city", "region", "country", "remote")  # = harmonization LocationKind


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


snapshot_postings = Table(
    "snapshot_postings",
    Base.metadata,
    Column("snapshot_id", ForeignKey("snapshots.id", ondelete="CASCADE"), primary_key=True),
    Column("posting_id", ForeignKey("postings.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_snapshot_postings_posting_id", "posting_id"),
)

posting_locations = Table(
    "posting_locations",
    Base.metadata,
    Column("posting_id", ForeignKey("postings.id", ondelete="CASCADE"), primary_key=True),
    Column("location_id", ForeignKey("locations.id", ondelete="CASCADE"), primary_key=True),
    Index("ix_posting_locations_location_id", "location_id"),
)


class Company(Base):
    __tablename__ = "companies"
    __table_args__ = (UniqueConstraint("source", "board_token"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(32))
    board_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"
    __table_args__ = (CheckConstraint(_in("status", RUN_STATUSES), name="status"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16))

    snapshots: Mapped[list["Snapshot"]] = relationship(back_populates="run")


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint("run_id", "company_id"),
        CheckConstraint(_in("status", SNAPSHOT_STATUSES), name="status"),
        Index("ix_snapshots_company_id_fetched_at", "company_id", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("scrape_runs.id"))
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16))
    posting_count: Mapped[int | None]  # NULL when failed: never read as 0 openings
    error_type: Mapped[str | None] = mapped_column(String(64))

    run: Mapped[ScrapeRun] = relationship(back_populates="snapshots")
    company: Mapped[Company] = relationship()
    postings: Mapped[list["PostingRecord"]] = relationship(secondary=snapshot_postings)


class PostingRecord(Base):
    """A posting's latest known state plus its open/close history on one company's board."""

    __tablename__ = "postings"
    __table_args__ = (
        UniqueConstraint("company_id", "external_id"),
        Index("ix_postings_company_id_closed_at", "company_id", "closed_at"),
        Index("ix_postings_role_family_seniority", "role_family", "seniority"),
        Index("ix_postings_taxonomy_version", "taxonomy_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    external_id: Mapped[str] = mapped_column(String(EXTERNAL_ID_MAX))
    title: Mapped[str] = mapped_column(String(TITLE_MAX))
    location_raw: Mapped[str | None] = mapped_column(Text)
    department: Mapped[str | None] = mapped_column(String(DEPARTMENT_MAX))
    url: Mapped[str] = mapped_column(Text)
    first_published: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    first_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Phase 1.3 harmonization (NULL until the harmonize command has run)
    role_family: Mapped[str | None] = mapped_column(String(32))
    seniority: Mapped[str | None] = mapped_column(String(16))
    taxonomy_version: Mapped[str | None] = mapped_column(String(16))
    harmonized_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    company: Mapped[Company] = relationship()
    locations: Mapped[list["Location"]] = relationship(secondary=posting_locations)


class Location(Base):
    """A canonical place; ``key`` is CanonicalLocation.key (kind|country|region|city)."""

    __tablename__ = "locations"
    __table_args__ = (
        UniqueConstraint("key"),
        CheckConstraint(_in("kind", LOCATION_KINDS), name="kind"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(16))
    country_code: Mapped[str | None] = mapped_column(String(2))
    region_code: Mapped[str | None] = mapped_column(String(6))
    city: Mapped[str | None] = mapped_column(String(128))
