"""Database engine and session management.

One SQLite file per clinic (PROJECT_PLAN.md D13, amended 2026-07-26). Engines are
cached per database URL, so a single process can serve the whole fleet while each
clinic's data stays in its own file. Isolation comes from the file boundary, not
from a `WHERE clinic_id` that a future edit could forget.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from clinic_bot.db.models import Base
from clinic_bot.settings import get_settings

_engines: dict[str, Engine] = {}
_factories: dict[str, sessionmaker[Session]] = {}


def _ensure_sqlite_dir(url: str) -> None:
    """SQLite will not create a missing parent directory; do it for the operator."""
    prefix = "sqlite:///"
    if url.startswith(prefix):
        db_path = Path(url[len(prefix) :])
        if db_path.parent and str(db_path.parent) not in ("", "."):
            db_path.parent.mkdir(parents=True, exist_ok=True)


def _resolve(url: str | None) -> str:
    return url or get_settings().database_url


def get_engine(url: str | None = None) -> Engine:
    key = _resolve(url)
    engine = _engines.get(key)
    if engine is not None:
        return engine

    _ensure_sqlite_dir(key)
    engine = create_engine(
        key,
        future=True,
        # SQLite defaults to a single-thread check that breaks under uvicorn's
        # threadpool. Our access is short and serialized by WAL + busy_timeout.
        connect_args={"check_same_thread": False, "timeout": 15}
        if key.startswith("sqlite")
        else {},
    )

    if key.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
            cur = dbapi_conn.cursor()
            # WAL lets the payment page read while the bot writes.
            cur.execute("PRAGMA journal_mode=WAL")
            # Without this, ON DELETE CASCADE is silently ignored by SQLite.
            cur.execute("PRAGMA foreign_keys=ON")
            cur.execute("PRAGMA busy_timeout=15000")
            cur.close()

    _engines[key] = engine
    return engine


def get_session_factory(url: str | None = None) -> sessionmaker[Session]:
    key = _resolve(url)
    factory = _factories.get(key)
    if factory is None:
        factory = sessionmaker(bind=get_engine(key), expire_on_commit=False, future=True)
        _factories[key] = factory
    return factory


@contextmanager
def session_scope(url: str | None = None) -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on any exception."""
    session = get_session_factory(url)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db(url: str | None = None) -> None:
    Base.metadata.create_all(get_engine(url))


def reset_engine() -> None:
    """Drop every cached engine/factory. Used by tests switching database URLs."""
    for engine in _engines.values():
        engine.dispose()
    _engines.clear()
    _factories.clear()
