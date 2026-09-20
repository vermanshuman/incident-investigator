from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Same database the target app writes to; the tools open it READ-ONLY.
    target_database_url: str = f"sqlite:///{(PROJECT_ROOT / 'data' / 'checkout.db').as_posix()}"
    target_repo_path: str = str(PROJECT_ROOT / "target-repo")

    default_window_minutes: int = 30
    max_rows: int = 200
    max_log_lines: int = 200
    max_diff_bytes: int = 20_000
    statement_timeout_seconds: float = 5.0


@lru_cache
def get_settings() -> Settings:
    return Settings()
