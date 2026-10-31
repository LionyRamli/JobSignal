"""Assembly checks: Alembic migrations and storage/schema.py must stay in lockstep."""

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect

from jobsignal.storage.db import make_engine
from jobsignal.storage.schema import Base

pytestmark = pytest.mark.integration


def _current_revision(url):
    with make_engine(url).connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def test_migration_history_has_a_single_head(alembic_cfg):
    assert len(ScriptDirectory.from_config(alembic_cfg).get_heads()) == 1


def test_upgrade_head_targets_the_configured_database(alembic_cfg, db_url):
    command.upgrade(alembic_cfg, "head")

    head = ScriptDirectory.from_config(alembic_cfg).get_current_head()
    assert _current_revision(db_url) == head


def test_migrations_are_reversible(alembic_cfg, db_url):
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "base")
    assert _current_revision(db_url) is None
    assert set(inspect(make_engine(db_url)).get_table_names()) <= {"alembic_version"}

    command.upgrade(alembic_cfg, "head")
    assert _current_revision(db_url) is not None


def test_models_match_migrated_schema(alembic_cfg, db_url):
    command.upgrade(alembic_cfg, "head")

    with make_engine(db_url).connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)

    assert diff == [], f"schema.py changed without a migration: {diff}"
