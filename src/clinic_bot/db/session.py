"""Database engine and session management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from clinic_bot.db.models import Base
from clinic_bot.settings import get_settings

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _ensure_sqlite_dir(url: str) -> None:
    """SQLite will not create a missing parent directory; do it for the operator."""
    prefix = "sqlite:///"
    if url.startswith(prefix):
        db_path = Path(url[len(prefix) :])
        if db_path.parent and str(db_path.parent) not in ("", "."):
            db_path.parent.mkdir(parents=True, exist_ok=True)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = get_settings().database_url
        _ensure_sqlite_dir(url)
        _engine = create_engine(
            url,
            future=True,
            # SQLite defaults to a single-thread check that breaks under uvicorn's
            # threadpool. Our access is short and serialized by WAL + busy_timeout.
            connect_args={"check_same_thread": False, "timeout": 15}
            if url.startswith("sqlite")
            else {},
        )

        if url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _set_sqlite_pragmas(dbapi_conn, _record):  # type: ignore[no-untyped-def]
                cur = dbapi_conn.cursor()
                # WAL lets the payment page read while the bot writes.
                cur.execute("PRAGMA journal_mode=WAL")
                # Without this, ON DELETE CASCADE is silently ignored by SQLite.
                cur.execute("PRAGMA foreign_keys=ON")
                cur.execute("PRAGMA busy_timeout=15000")
                cur.close()

    return _engine


def get_session_factory() -> sessionmaker[Session]:
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SessionFactory


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional scope. Commits on success, rolls back on any exception."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def init_db() -> None:
    Base.metadata.create_all(get_engine())


def reset_engine() -> None:
    """Drop cached engine/factory. Used by tests switching database URLs."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None
