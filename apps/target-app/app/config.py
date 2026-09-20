from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Checkout service configuration. Values here are the deploy config that
    fault scenarios tamper with (pool size, provider settings, flags)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    target_database_url: str = "sqlite:///./data/checkout.db"

    # Database connection pool
    db_pool_size: int = 10
    db_max_overflow: int = 5
    db_pool_timeout_seconds: int = 3

    # Payment provider
    payment_provider_url: str = "https://payments.example.com/v1/charge"
    payment_provider_api_key: str = "pk_live_7f3a9c2e"
    payment_provider_timeout_seconds: float = 2.0

    # Business rules
    shipping_fee_international: float = 15.0
    free_shipping_threshold: float = 999.0

    # Metrics sampler
    metrics_sample_interval_seconds: int = 5


@lru_cache
def get_settings() -> Settings:
    return Settings()
