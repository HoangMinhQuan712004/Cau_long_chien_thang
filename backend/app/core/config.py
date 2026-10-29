import base64
import binascii
from functools import lru_cache
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _valid_fernet_key(key: str) -> bool:
    try:
        return len(base64.urlsafe_b64decode(key.encode())) == 32 and len(key) == 44
    except (ValueError, binascii.Error):
        return False


# SĐT Admin mẫu (link dev, máy local) – không bao giờ dùng trên production
SAMPLE_ADMIN_PHONE = "0912345678"


class Settings(BaseSettings):
    # hide_input_in_errors: lỗi cấu hình lúc khởi động không in giá trị env (DATABASE_URL, khóa…)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    APP_NAME: str = "Cau Long API"
    # development (máy dev) | staging (link dev công khai) | production.
    # Giá trị khác -> không khởi động.
    ENV: Literal["development", "staging", "production"] = "development"
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
    # Số proxy tin cậy GHI X-Forwarded-For trước API để lấy IP thật của khách.
    # Prod/dev (Caddy -> Next -> API) = 1: chỉ Caddy ghi XFF, Next không nối thêm.
    # 0 = dùng IP kết nối trực tiếp.
    TRUSTED_PROXY_COUNT: int = 0
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_PER_MINUTE: int = 120  # mặc định toàn API, theo IP
    MAX_BODY_BYTES: int = 64 * 1024

    # Booking engine: mỗi bản chạy phục vụ một tenant
    TENANT_ID: int = 1

    # Nghiệp vụ sân
    TIMEZONE: str = "Asia/Ho_Chi_Minh"
    # Giờ mở cửa, khung, giữ chỗ… cấu hình theo sân trong booking engine (T-005, T-006)

    # Đặt online + SePay (T-008, ADR-007): dự phòng khi Admin chưa lưu cài đặt trên trang (T-012).
    SEPAY_BANK_CODE: str = ""  # mã NH cho qr.sepay.vn (vd "Vietcombank")
    SEPAY_BANK_NAME: str = ""
    SEPAY_ACCOUNT_NUMBER: str = ""
    SEPAY_ACCOUNT_NAME: str = ""
    SEPAY_WEBHOOK_SECRET: str = ""
    # 0 = không chặn theo tuổi timestamp (ADR-001 §2); > 0: lệch quá số giây này -> 401
    SEPAY_TIMESTAMP_TOLERANCE_SECONDS: int = 0
    ONLINE_HOLD_MINUTES: int = 5
    # Ân hạn nhận tiền báo trễ sau khi hết giữ chỗ; trong ân hạn khung vẫn bị chiếm
    ONLINE_HOLD_GRACE_SECONDS: int = 60
    # Chỉ dev/staging: POST /payments/dev/simulate. ENV=production + bật -> app không khởi động
    PAYMENTS_SIMULATE: bool = False
    # Khóa mã hóa khóa webhook lưu trong DB (T-012): Fernet = 32 byte base64 urlsafe (44 ký tự).
    # Bắt buộc ở staging/production; development thiếu -> sinh tạm + cảnh báo.
    PAYMENTS_ENCRYPTION_KEY: str | None = None

    # Đăng nhập, phiên, OTP (T-013, ADR-008)
    ADMIN_SESSION_HOURS: int = 12  # phiên Admin / nhân viên hết hạn cứng, không gia hạn
    LOGIN_MAX_ATTEMPTS: int = 5  # sai liên tiếp N lần -> tạm khóa tài khoản
    LOGIN_LOCK_MINUTES: int = 15
    LOGIN_IP_MAX_ATTEMPTS: int = 20  # sai từ một IP trong cửa sổ -> chặn IP
    LOGIN_IP_WINDOW_MINUTES: int = 15
    REGISTER_IP_MAX_PER_HOUR: int = 10
    OTP_TTL_MINUTES: int = 5
    OTP_MAX_ATTEMPTS: int = 5  # nhập sai N lần -> mã chết
    OTP_RESEND_SECONDS: int = 60
    OTP_MAX_PER_HOUR: int = 5  # mỗi SĐT (kể cả SĐT chưa có tài khoản)
    OTP_IP_MAX_PER_HOUR: int = 20
    OTP_RESET_TOKEN_MINUTES: int = 10  # hạn đặt mật khẩu mới sau khi nhập đúng mã
    BOOKING_PHONE_TOKEN_MINUTES: int = 30  # hạn phone_token của đặt online
    # Chỉ link dev / máy dev: mã OTP của khách trả trong response; production + bật -> dừng
    OTP_TEST_MODE: bool = False
    # Zalo ZNS (gửi OTP) – làm sau; thiếu -> production tạm ngưng đặt online + quên mật khẩu
    ZALO_APP_ID: str = ""
    ZALO_SECRET_KEY: str = ""
    ZALO_REFRESH_TOKEN: str = ""
    ZALO_TEMPLATE_OTP: str = ""
    # Client ID Google (công khai); trống -> tắt đăng nhập Google
    GOOGLE_CLIENT_ID: str = ""

    # Admin đầu tiên: migration gán SĐT này cho Admin chưa có SĐT; seed tạo Admin khi chưa có.
    # Production phải đặt rõ SĐT thật (mặc định / SĐT mẫu -> migration + seed dừng)
    FIRST_ADMIN_PHONE: str = SAMPLE_ADMIN_PHONE
    FIRST_ADMIN_PASSWORD: str = "Admin@12345"

    @model_validator(mode="after")
    def _check_deployed(self):
        if self.is_deployed and (self.SECRET_KEY == "change-me" or len(self.SECRET_KEY) < 32):
            raise ValueError(f"SECRET_KEY phải được đặt (>= 32 ký tự) khi ENV={self.ENV}")
        if self.is_production and self.PAYMENTS_SIMULATE:
            raise ValueError("PAYMENTS_SIMULATE không được bật khi ENV=production")
        if self.is_production and self.OTP_TEST_MODE:
            raise ValueError("OTP_TEST_MODE không được bật khi ENV=production")
        if self.is_deployed and not _valid_fernet_key(self.PAYMENTS_ENCRYPTION_KEY or ""):
            raise ValueError(
                f"PAYMENTS_ENCRYPTION_KEY phải là 32 byte base64 urlsafe khi ENV={self.ENV}"
            )
        return self

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.TIMEZONE)

    @property
    def is_production(self) -> bool:
        return self.ENV == "production"

    @property
    def first_admin_phone_is_sample(self) -> bool:
        """Production mà ``FIRST_ADMIN_PHONE`` không đặt rõ (đang lấy mặc định) hoặc là SĐT mẫu."""
        if not self.is_production:
            return False
        digits = "".join(ch for ch in self.FIRST_ADMIN_PHONE if ch.isdigit())
        sample = SAMPLE_ADMIN_PHONE.removeprefix("0")
        return "FIRST_ADMIN_PHONE" not in self.model_fields_set or digits in (
            "0" + sample,
            "84" + sample,
        )

    @property
    def zalo_configured(self) -> bool:
        return all(
            (
                self.ZALO_APP_ID,
                self.ZALO_SECRET_KEY,
                self.ZALO_REFRESH_TOKEN,
                self.ZALO_TEMPLATE_OTP,
            )
        )

    @property
    def otp_channel_ready(self) -> bool:
        """Có đường gửi OTP: Zalo đủ cấu hình hoặc chế độ thử (dev)."""
        return self.zalo_configured or self.OTP_TEST_MODE

    @property
    def is_deployed(self) -> bool:
        """Chạy trên server (link dev hoặc production): kiểm SECRET_KEY, tắt /docs."""
        return self.ENV in ("staging", "production")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
