import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.analysis_db import ensure_analysis_db_shape
from app.config import get_settings
from app.db_maintenance import ensure_database_shape
from app.routers import analysis, meta, sessions

_BACKEND_DIR = Path(__file__).resolve().parent.parent

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
    ensure_analysis_db_shape()
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
    app.include_router(analysis.router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # Serve the built frontend (frontend/dist) so the tool can be hosted through
    # the backend, not only via the Vite dev server. Mounted LAST so the API
    # routers above always win; skipped when the bundle is absent (pure dev).
    if settings.serve_frontend:
        dist = Path(settings.frontend_dist_dir)
        if not dist.is_absolute():
            dist = (_BACKEND_DIR / dist).resolve()
        if dist.is_dir():
            app.mount("/", StaticFiles(directory=str(dist), html=True), name="frontend")
        else:
            log.warning("serve_frontend on but dist dir not found: %s", dist)

    return app


app = create_app()
