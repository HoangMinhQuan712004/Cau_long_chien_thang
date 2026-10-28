"""Cấu hình nhận tiền online đang hiệu lực (T-012 AC8, AC9).

- Có dòng ``payments.settings`` -> **nguồn duy nhất** (không trộn với ``.env``).
- Chưa có dòng -> ``SEPAY_*`` của ``.env`` (tương thích T-008).
- Cache trong tiến trình ≤ 10 giây; xóa khi Admin lưu cài đặt.
- Khóa webhook lưu mã hóa Fernet bằng ``PAYMENTS_ENCRYPTION_KEY``; không trả ra API / log / audit.
"""

import logging
import time
from dataclasses import dataclass
from datetime import datetime

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.payments.banks import bank_name, qr_bank_param
from app.modules.payments.models import PaymentSettings

logger = logging.getLogger(__name__)

CACHE_SECONDS = 10.0
MISSING_ORDER = ("bank", "account_number", "account_name", "webhook_secret")


@dataclass(frozen=True)
class PaymentConfig:
    source: str  # "db" | "env"
    bank_code: str | None
    bank_name: str | None
    account_number: str | None
    account_name: str | None
    webhook_secret: str | None  # rõ – chỉ dùng trong tiến trình, không bao giờ trả ra
    online_toggle: bool
    secret_last4: str | None = None
    last_webhook_at: datetime | None = None
    updated_at: datetime | None = None
    updated_by_label: str | None = None

    @property
    def missing(self) -> list[str]:
        have = {
            "bank": bool(self.bank_code),
            "account_number": bool(self.account_number),
            "account_name": bool(self.account_name),
            "webhook_secret": bool(self.webhook_secret),
        }
        return [k for k in MISSING_ORDER if not have[k]]

    @property
    def online_enabled(self) -> bool:
        return self.online_toggle and not self.missing

    @property
    def qr_bank(self) -> str:
        return qr_bank_param(self.bank_code or "")


# ------------------------------------------------------------------ mã hóa khóa webhook

_dev_key: bytes | None = None


def _fernet() -> Fernet:
    global _dev_key
    if settings.PAYMENTS_ENCRYPTION_KEY:
        return Fernet(settings.PAYMENTS_ENCRYPTION_KEY.encode())
    # Settings đã chặn staging/production thiếu khóa; development: khóa tạm cho phiên chạy này
    if _dev_key is None:
        _dev_key = Fernet.generate_key()
        logger.warning(
            "PAYMENTS_ENCRYPTION_KEY is not set: using a temporary key (development only); "
            "webhook secrets saved now cannot be read after a restart"
        )
    return Fernet(_dev_key)


def encrypt_secret(secret: str) -> bytes:
    return _fernet().encrypt(secret.encode())


def decrypt_secret(token: bytes | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(bytes(token)).decode()
    except InvalidToken:
        logger.warning("Stored webhook secret cannot be decrypted with the current key")
        return None


# ------------------------------------------------------------------ đọc cấu hình


def _from_env() -> PaymentConfig:
    secret = settings.SEPAY_WEBHOOK_SECRET or None
    code = settings.SEPAY_BANK_CODE or None
    return PaymentConfig(
        source="env",
        bank_code=code,
        bank_name=settings.SEPAY_BANK_NAME or (bank_name(code) if code else None),
        account_number=settings.SEPAY_ACCOUNT_NUMBER or None,
        account_name=settings.SEPAY_ACCOUNT_NAME or None,
        webhook_secret=secret,
        online_toggle=True,  # T-008: đủ biến .env = bật
        secret_last4=secret[-4:] if secret else None,
    )


def from_row(row: PaymentSettings) -> PaymentConfig:
    return PaymentConfig(
        source="db",
        bank_code=row.bank_code,
        bank_name=row.bank_name,
        account_number=row.account_number,
        account_name=row.account_name,
        webhook_secret=decrypt_secret(row.webhook_secret_enc),
        online_toggle=row.online_toggle,
        secret_last4=row.secret_last4,
        last_webhook_at=row.last_webhook_at,
        updated_at=row.updated_at,
        updated_by_label=row.updated_by_label,
    )


# Cache theo tiến trình: (thời điểm đọc, dòng DB đã chuyển thành PaymentConfig hoặc None)
_cache: tuple[float, PaymentConfig | None] | None = None


def clear_cache() -> None:
    global _cache
    _cache = None


async def load(session: AsyncSession, fresh: bool = False) -> PaymentConfig:
    """Cấu hình hiệu lực. ``.env`` luôn đọc trực tiếp (không cache) khi chưa có dòng DB."""
    global _cache
    now = time.monotonic()
    if fresh or _cache is None or now - _cache[0] > CACHE_SECONDS:
        row = await session.scalar(
            select(PaymentSettings).where(PaymentSettings.tenant_id == settings.TENANT_ID)
        )
        _cache = (now, from_row(row) if row is not None else None)
    db_config = _cache[1]
    return db_config if db_config is not None else _from_env()
