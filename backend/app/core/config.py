from datetime import time
from functools import lru_cache
from ipaddress import IPv4Network, IPv6Network, ip_network
from zoneinfo import ZoneInfo

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@lru_cache
def parse_networks(raw: str) -> tuple[IPv4Network | IPv6Network, ...]:
    """`"127.0.0.1, 172.16.0.0/12"` ⇒ các mạng; IP lẻ = mạng /32 (/128)."""
    return tuple(ip_network(part.strip(), strict=False) for part in raw.split(",") if part.strip())


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
    # Phiên quản trị hết hạn cứng sau N giờ
    ADMIN_SESSION_HOURS: int = 12
    LOGIN_MAX_ATTEMPTS: int = 5  # sai liên tiếp N lần ⇒ tạm khóa (BR-004)
    LOGIN_LOCK_MINUTES: int = 15
    # Chặn IP sai quá N lần trong M phút
    LOGIN_IP_MAX_ATTEMPTS: int = 20
    LOGIN_IP_WINDOW_MINUTES: int = 15
    # Số lần đăng ký tối đa mỗi IP / giờ
    REGISTER_IP_MAX_PER_HOUR: int = 10
    # Proxy tin cậy (IP/CIDR, dấu phẩy) được đọc X-Forwarded-For
    TRUSTED_PROXIES: str = "127.0.0.1,::1"
    # OTP Zalo (quên mật khẩu, xác minh SĐT)
    OTP_TTL_MINUTES: int = 5
    OTP_MAX_ATTEMPTS: int = 5  # nhập sai N lần ⇒ hủy mã
    OTP_RESEND_SECONDS: int = 60
    OTP_MAX_PER_HOUR: int = 5  # mỗi SĐT (kể cả SĐT chưa đăng ký)
    OTP_IP_MAX_PER_HOUR: int = 20
    OTP_RESET_TOKEN_MINUTES: int = 10  # hạn đặt mật khẩu mới sau khi nhập đúng mã
    # Zalo ZNS; trống ⇒ chưa gửi
    ZALO_APP_ID: str = ""
    ZALO_SECRET_KEY: str = ""
    ZALO_REFRESH_TOKEN: str = ""
    ZALO_TEMPLATE_OTP: str = ""
    # Client ID Google; trống ⇒ tắt /auth/google
    GOOGLE_CLIENT_ID: str = ""

    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # Nghiệp vụ sân
    TIMEZONE: str = "Asia/Ho_Chi_Minh"
    OPEN_TIME: time = time(5, 0)
    CLOSE_TIME: time = time(23, 0)
    SLOT_MINUTES: int = 30
    MIN_BOOKING_MINUTES: int = 60
    MAX_ADVANCE_DAYS: int = 30
    HOLD_MINUTES: int = 10  # thời gian giữ slot khi chờ thanh toán

    # Tài khoản Admin do seed tạo
    FIRST_ADMIN_PHONE: str = "0912345678"
    FIRST_ADMIN_PASSWORD: str = "Admin@12345"

    @field_validator("TRUSTED_PROXIES")
    @classmethod
    def _check_trusted_proxies(cls, value: str) -> str:
        parse_networks(value)  # sai định dạng ⇒ báo ngay lúc khởi động
        return value

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
