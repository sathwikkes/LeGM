"""SQLAlchemy engine/session factory.

Default is SQLite at data/legm.db. Set LEGM_DATABASE_URL to point elsewhere
(e.g. postgresql+psycopg://...). Only portable SQL is used in this package.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_ENV_VAR = "LEGM_DATABASE_URL"
DEFAULT_SQLITE_PATH = Path("data") / "legm.db"


def database_url(url: str | None = None) -> str:
    if url:
        return url
    if env := os.environ.get(DATABASE_ENV_VAR):
        return env
    DEFAULT_SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{DEFAULT_SQLITE_PATH}"


def make_engine(url: str | None = None) -> Engine:
    return create_engine(database_url(url), future=True)


def init_db(engine: Engine) -> None:
    """Create missing tables, then add any columns the models gained since the DB was created.

    Additive only (ALTER TABLE ... ADD COLUMN works on SQLite and Postgres); nothing is
    dropped or retyped. A real migration tool can replace this once the schema settles.
    """
    from legm.data.models import Base

    Base.metadata.create_all(engine)
    sync_columns(engine, Base.metadata)


def sync_columns(engine: Engine, metadata) -> list[str]:
    inspector = inspect(engine)
    added: list[str] = []
    with engine.begin() as conn:
        for table in metadata.sorted_tables:
            existing = {c["name"] for c in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                col_type = column.type.compile(dialect=engine.dialect)
                nullable = "" if column.nullable else " NOT NULL"
                default = ""
                if column.default is not None and getattr(column.default, "is_scalar", False):
                    arg = column.default.arg
                    default = f" DEFAULT {arg!r}" if isinstance(arg, str) else f" DEFAULT {arg}"
                elif not column.nullable:
                    nullable = ""  # cannot add NOT NULL without a default to a populated table
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {col_type}{nullable}{default}'))
                added.append(f"{table.name}.{column.name}")
    return added


@contextmanager
def session_scope(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, future=True, expire_on_commit=False)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
