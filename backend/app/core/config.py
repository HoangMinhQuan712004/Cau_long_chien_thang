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

    # Bảo mật (ADR-004)
    # Origin được phép gửi request ghi kèm cookie phiên (chống CSRF):
    # site prod / dev / localhost dev
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]
    # Số proxy tin cậy đứng trước API (Caddy -> Next -> API = 2) để lấy IP thật từ X-Forwarded-For.
    # 0 = dùng IP kết nối trực tiếp.
    TRUSTED_PROXY_COUNT: int = 0
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 120  # mặc định toàn API, theo IP
    MAX_BODY_BYTES: int = 64 * 1024

    # Booking engine: mỗi bản chạy phục vụ một tenant
    TENANT_ID: int = 1

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
