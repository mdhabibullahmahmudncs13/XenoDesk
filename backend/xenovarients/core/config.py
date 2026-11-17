"""Application settings. All configuration comes from the environment; no secrets have defaults."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    environment: str = "local"
    debug: bool = False
    log_level: str = "INFO"

    # --- Database ---
    # Annotated as str, not PostgresDsn: the asyncpg scheme ("postgresql+asyncpg://")
    # is not a valid PostgresDsn, and pydantic would reject the default.
    database_url: str = Field(
        default="postgresql+asyncpg://xenovarients:xenovarients@localhost:5432/xenovarients"
    )
    # Migrations need DDL rights, so they run as the schema owner. The app connects as
    # a restricted role that is subject to Row Level Security and cannot ALTER or DROP.
    migration_database_url: str | None = None
    db_echo: bool = False

    # --- Redis ---
    redis_url: str = Field(default="redis://localhost:6379/0")

    # --- Auth ---
    # No default: a missing secret must fail loudly, not silently fall back to a known value.
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 14

    # --- Provider secrets (optional until the corresponding feature is enabled) ---
    meta_app_secret: str | None = None
    meta_app_id: str | None = None
    sms_gateway_key: str | None = None
    email_api_key: str | None = None
    email_from_domain: str | None = None
    llm_api_key: str | None = None
    llm_model: str = "claude-sonnet-4-5"

    # --- Webhook signature verification ---
    webhook_timestamp_tolerance_seconds: int = 300

    # --- Outbound delivery ---
    max_delivery_attempts: int = 3
    delivery_retry_base_seconds: int = 30

    # --- Outbound rate limits (sends per business per channel per minute) ---
    # Zero means "use the built-in default for that channel".
    rate_limit_email: int = 0
    rate_limit_sms: int = 0
    rate_limit_messenger: int = 0
    rate_limit_whatsapp: int = 0

    # --- Business defaults (OD-02, OD-08) ---
    default_timezone: str = "Asia/Dhaka"
    default_currency: str = "BDT"
    review_delay_days: int = 3
    review_send_window_start: str = "09:00"
    review_send_window_end: str = "20:00"
    review_reply_window_days: int = 14

    @field_validator("jwt_secret")
    @classmethod
    def _reject_weak_secret(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("jwt_secret must be at least 32 characters")
        return v

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()
