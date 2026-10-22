from datetime import time
from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    APP_NAME: str = "Cau Long API"
    ENV: str = "development"
    API_PREFIX: str = "/api/v1"

    DATABASE_URL: str = "postgresql+asyncpg://caulong:caulong@localhost:5432/caulong"
    REDIS_URL: str = "redis://localhost:6379/0"

    # Auth
    SECRET_KEY: str = "change-me"
    ACCESS_TOKEN_MINUTES: int = 30
    REFRESH_TOKEN_DAYS: int = 14
    COOKIE_DOMAIN: str | None = None
    COOKIE_SECURE: bool = False

    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # Nghiệp vụ sân
    TIMEZONE: str = "Asia/Ho_Chi_Minh"
    OPEN_TIME: time = time(5, 0)
    CLOSE_TIME: time = time(23, 0)
    SLOT_MINUTES: int = 30
    MIN_BOOKING_MINUTES: int = 60
    MAX_ADVANCE_DAYS: int = 30
    HOLD_MINUTES: int = 10  # thời gian giữ slot khi chờ thanh toán

    # Seed
    FIRST_ADMIN_EMAIL: str = "admin@example.com"
    FIRST_ADMIN_PASSWORD: str = "admin12345"

    @model_validator(mode="after")
    def _check_production(self):
        if self.is_production and (self.SECRET_KEY == "change-me" or len(self.SECRET_KEY) < 32):
            raise ValueError("SECRET_KEY phải được đặt (>= 32 ký tự) khi ENV=production")
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.TIMEZONE)

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
