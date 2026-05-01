from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Always resolve backend/.env by path relative to this file so the server
# works regardless of what directory uvicorn is launched from.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
_ENV_FILE = str(_BACKEND_DIR / ".env")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOPT_",
        env_file=(_ENV_FILE, ".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    host: str = "0.0.0.0"
    port: int = 8000
    public_url: str = "http://localhost:8000"
    database_url: str = "sqlite:///./data/mopt_study.db"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    client_secret: str = "dev-client"
    researcher_secret: str = "dev-researcher"
    fernet_key: str | None = None
    solve_timeout_sec: float = 120.0
    derivation_timeout_sec: float = 45.0
    default_gemini_model: str = "gemini-3.1-flash-lite-preview"
    gemini_model_suggestions: str = "gemini-3.1-flash-lite-preview,gemini-3-flash-preview"
    # Comma-separated extra directories (repo-relative or absolute): mopt_manifest.toml and/or register_ports.py
    problem_paths: str = ""

    @property
    def gemini_model_suggestions_list(self) -> list[str]:
        return [m.strip() for m in self.gemini_model_suggestions.split(",") if m.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
