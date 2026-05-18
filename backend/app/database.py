from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _sqlite_connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def get_engine():
    settings = get_settings()
    url = settings.database_url
    if url.startswith("sqlite:///"):
        path_part = url[len("sqlite:///") :].lstrip("/")
        if path_part and not path_part.startswith(":"):
            p = Path(path_part)
            if p.parent != Path("."):
                p.parent.mkdir(parents=True, exist_ok=True)
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
