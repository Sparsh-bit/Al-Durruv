from functools import lru_cache

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEV_JWT_SECRET = "dev-only-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    environment: str = "development"  # set to "production" on Railway
    database_url: str = "postgresql+psycopg://trade:trade@localhost:5433/trade_intel"
    # Neon direct (non-pooled) URL for migrations; falls back to DATABASE_URL when empty.
    database_url_unpooled: str = ""
    jwt_secret: str = DEV_JWT_SECRET
    jwt_ttl_minutes: int = 60 * 12
    cors_origins: str = "http://localhost:5173"
    frontend_dist: str = ""  # path to the built React app; defaults to ../frontend/dist

    admin_email: str = "admin@example.com"
    admin_password: str = ""

    anthropic_api_key: str = ""
    claude_model: str = "claude-haiku-5-5"
    research_max_searches: int = 5

    comtrade_subscription_key: str = ""
    comtrade_min_interval_s: float = 1.5
    comtrade_cache_ttl_hours: int = 24 * 7
    trade_years_back: int = 6

    # ISO3 of the exporter's own country; enables "your country's share" in rankings.
    home_country_iso3: str = ""

    @field_validator("database_url", "database_url_unpooled")
    @classmethod
    def _psycopg_driver(cls, v: str) -> str:
        # Neon and Railway hand out postgres:// or postgresql:// URLs; SQLAlchemy needs the psycopg driver name.
        if not v:
            return v
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix) :]
        return v

    @model_validator(mode="after")
    def _production_safety(self):
        if self.is_production:
            if self.jwt_secret == DEV_JWT_SECRET or len(self.jwt_secret) < 32:
                raise ValueError("JWT_SECRET must be set to a random string of 32+ characters in production.")
            if "localhost" in self.database_url:
                raise ValueError("DATABASE_URL points at localhost in production; set it to the Neon URL.")
        return self

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
