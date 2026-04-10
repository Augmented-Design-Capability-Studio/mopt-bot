import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db_maintenance import ensure_database_shape
from app.routers import meta, sessions

LOG_FORMAT = "%(asctime)s %(levelname)s: %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def configure_logging() -> None:
    formatter = logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT)
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, datefmt=LOG_DATE_FORMAT)
    else:
        root.setLevel(logging.INFO)
        for handler in root.handlers:
            handler.setFormatter(formatter)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(logger_name)
        logger.setLevel(logging.INFO)
        for handler in logger.handlers:
            handler.setFormatter(formatter)


log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    ensure_database_shape()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="MOPT Study API",
        description="Metaheuristic assistant study backend",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(sessions.router)
    app.include_router(meta.router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()
