from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MOPT_",
        env_file=(".env", "../.env"),
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
    default_gemini_model: str = "gemini-2.0-flash"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
