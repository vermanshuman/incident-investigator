from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Local dev without Docker falls back to SQLite; compose sets Postgres via .env.
    database_url: str = "sqlite:///./investigator.db"
    redis_url: str = "redis://localhost:6379/0"
    session_secret: str = "change-me"
    cors_origins: list[str] = ["http://localhost:3000"]

    github_token: str = ""
    github_repo: str = ""

    otel_service_name: str = "investigator-api"
    otel_exporter_otlp_endpoint: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
