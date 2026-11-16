"""Tiện ích dùng chung cho các dịch vụ đặt chỗ của engine (T-006)."""

import base64
import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor
from app.core.config import settings
from app.core.errors import AppError
from app.modules.booking_engine.dto import Actor
from app.modules.booking_engine.models import Tenant
from app.modules.booking_engine.schedules import to_hhmm
from app.modules.booking_engine.tenant import get_tenant, tenant_settings, tz_of

EXCLUSION_VIOLATION = "23P01"

PAST_SLOT = "Không thể đặt khung giờ đã qua."
STALE_ITEM = "Booking này vừa được cập nhật ở máy khác. Vui lòng xem lại."


@dataclass(frozen=True)
class Ctx:
    tenant: Tenant
    tz: ZoneInfo
    now: datetime
    today: date

    @property
    def settings(self) -> dict:
        return tenant_settings(self.tenant)

    @property
    def code_prefix(self) -> str:
        return str(self.settings["code_prefix"])

    def at(self, day: date, minute: int) -> datetime:
        """Thời điểm ``minute`` phút sau 0h ngày ``day`` (cho phép 24:00)."""
        return datetime.combine(day, time(), self.tz) + timedelta(minutes=minute)

    def minute_of(self, day: date, moment: datetime) -> int:
        return int((moment - datetime.combine(day, time(), self.tz)).total_seconds() // 60)

    def hhmm(self, day: date, moment: datetime) -> str:
        return to_hhmm(self.minute_of(day, moment))


async def context(session: AsyncSession, tenant_id: int, for_update: bool = False) -> Ctx:
    tenant = await get_tenant(session, tenant_id, for_update=for_update)
    tz = tz_of(tenant)
    now = datetime.now(tz)
    return Ctx(tenant=tenant, tz=tz, now=now, today=now.date())


def audit_actor(actor: Actor) -> AuditActor:
    return AuditActor(type=actor.type, id=actor.id, label=actor.label)


def sqlstate(e: IntegrityError) -> str | None:
    return getattr(e.orig, "sqlstate", None)


def not_found(what: str = "dữ liệu") -> AppError:
    return AppError("E-NOT-FOUND", f"Không tìm thấy {what}.", 404)


def not_sold(message: str) -> AppError:
    return AppError("E-CFG-10", message, 422)


def profile_label(kind: str, member_code: str | None, tier: str | None) -> str:
    if kind == "member":
        return f"Hội viên ({member_code} · Hạng {tier})" if tier else f"Hội viên ({member_code})"
    return "Hồ sơ tạm"


def token_hash(token: str) -> bytes:
    """SHA-256 của token trang thanh toán – DB chỉ lưu giá trị này (ADR-007)."""
    return hashlib.sha256(token.encode()).digest()


def checkout_token(checkout_id: uuid.UUID) -> str:
    """Token trang thanh toán = HMAC(SECRET_KEY, id lượt): tính lại được để trả cho chủ đơn khi
    bị chặn đặt mới (E-WEB-4); DB vẫn chỉ lưu ``token_hash``."""
    mac = hmac.new(
        settings.SECRET_KEY.encode(), f"checkout:{checkout_id}".encode(), hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(mac).rstrip(b"=").decode()


def recover_token(checkout_id: uuid.UUID, stored_hash: bytes) -> str | None:
    """Token của lượt nếu cấp theo ``checkout_token`` (so hash thời gian cố định); lượt cũ cấp
    token ngẫu nhiên -> None."""
    token = checkout_token(checkout_id)
    return token if hmac.compare_digest(token_hash(token), stored_hash) else None
