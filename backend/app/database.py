from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings

# Anchor relative sqlite paths to the backend directory so the DB always
# lands in backend/data regardless of the cwd the server/tests/scripts are
# launched from. Without this, a relative URL like "sqlite:///./data/..."
# resolves against the current working directory and spawns a stray
# /data/mopt_study.db wherever the process happened to start (repo root,
# etc.). _BACKEND_DIR == .../backend (this file is backend/app/database.py).
_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Base(DeclarativeBase):
    pass


def _sqlite_connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _resolve_sqlite_url(url: str) -> str:
    """Rewrite a relative sqlite file URL to an absolute, backend-anchored
    path and ensure its parent directory exists. Non-sqlite URLs, in-memory
    sqlite (``:memory:``), and already-absolute paths pass through unchanged
    (other than parent-dir creation)."""
    if not url.startswith("sqlite:///"):
        return url
    path_part = url[len("sqlite:///") :]
    if not path_part or path_part.startswith(":"):
        return url
    p = Path(path_part)
    if not p.is_absolute():
        p = (_BACKEND_DIR / p).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{p.as_posix()}"


def get_engine():
    settings = get_settings()
    url = _resolve_sqlite_url(settings.database_url)
    return create_engine(
        url,
        connect_args=_sqlite_connect_args(url),
        pool_pre_ping=True,
    )


@event.listens_for(Engine, "connect")
def _enable_sqlite_fk(dbapi_connection, _):
    # SQLite disables FK enforcement by default per connection. Without
    # this, `ON DELETE CASCADE` declared in the schema is silently inert
    # and child rows orphan when their parent session is deleted (we hit
    # this — 800+ orphan session_snapshots rows accumulated before we
    # noticed). Listener fires for every new connection from any engine,
    # so pool reuse is covered. No-op on non-SQLite DBAPIs.
    if dbapi_connection.__class__.__module__.startswith("sqlite3"):
        cur = dbapi_connection.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
