from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://trade:trade@localhost:5433/trade_intel"
    jwt_secret: str = "dev-only-change-me"
    jwt_ttl_minutes: int = 60 * 12
    cors_origins: str = "http://localhost:5173"

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

    @property
    def ai_enabled(self) -> bool:
        return bool(self.anthropic_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()
