from pathlib import Path

from sqlalchemy import create_engine
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


engine = get_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
