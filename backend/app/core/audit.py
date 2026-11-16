"""Nhật ký thao tác append-only (SRS BR-019, ADR-004 S14).

``audit(...)`` chỉ ``session.add`` – ghi trong **cùng transaction** với thao tác nghiệp vụ
(nghiệp vụ rollback thì nhật ký cũng không có). Bảng được trigger bảo vệ (migration):
UPDATE / TRUNCATE -> lỗi; DELETE chỉ cho dòng cũ hơn 12 tháng (job dọn ``purge_expired``).
"""

import ipaddress
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, DateTime, String, func, text
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.context import client_ip, request_id
from app.core.db import Base

ACTOR_TYPES = ("admin", "staff", "customer", "system", "web")
RETENTION = "12 months"


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(
            "actor_type IN ('admin', 'staff', 'customer', 'system', 'web')", name="actor_type"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    actor_type: Mapped[str] = mapped_column(String(20))
    actor_id: Mapped[int | None] = mapped_column(BigInteger)
    actor_label: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(60), index=True)
    entity_type: Mapped[str] = mapped_column(String(40))
    entity_code: Mapped[str | None] = mapped_column(String(40), index=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    ip: Mapped[str | None] = mapped_column(INET)
    request_id: Mapped[str | None] = mapped_column(String(64))


@dataclass(frozen=True)
class AuditActor:
    type: str  # một trong ACTOR_TYPES
    id: int | None
    label: str


SYSTEM_ACTOR = AuditActor(type="system", id=None, label="Hệ thống")


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def audit(
    session: AsyncSession,
    actor: AuditActor,
    action: str,
    entity_type: str,
    entity_code: str | None,
    detail: dict[str, Any] | None = None,
) -> None:
    """Thêm một dòng nhật ký vào transaction hiện tại.

    ``detail`` dựng bằng ``audit_detail``; KHÔNG chứa mật khẩu, token. SĐT ghi đầy đủ
    (chỉ Admin xem, SRS Lịch sử thao tác BR-007).
    """
    session.add(
        AuditLog(
            actor_type=actor.type,
            actor_id=actor.id,
            actor_label=actor.label,
            action=action,
            entity_type=entity_type,
            entity_code=entity_code,
            detail=detail or {},
            ip=_valid_ip(client_ip()),
            request_id=request_id(),
        )
    )


# ---------------------------------- nội dung dòng (SRS Lịch sử thao tác BR-004, 006, 008)

Value = str | int | bool | None


def audit_change(field: str, before: Value, after: Value) -> dict[str, Value]:
    """Một ô đã đổi: "Tên ô: trước → sau"; ``before`` None = tạo mới ("(trống)")."""
    return {"field": field, "before": before, "after": after}


def audit_changes(
    labels: Mapping[str, str], before: Mapping[str, Value], after: Mapping[str, Value]
) -> list[dict[str, Value]]:
    """Các ô đổi giá trị theo thứ tự ``labels`` (tên trường -> tên ô); ô không đổi thì bỏ."""
    return [
        audit_change(label, before.get(key), after.get(key))
        for key, label in labels.items()
        if before.get(key) != after.get(key)
    ]


def audit_detail(
    target_code: str | None,
    target_name: str | None = None,
    changes: list[dict[str, Value]] | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """``detail`` chuẩn: đối tượng chụp tên lúc làm (không tra lại theo mã) + danh sách ô đổi."""
    return {
        "target": {"code": target_code, "name": target_name},
        "changes": changes or [],
        **extra,
    }


async def purge_expired(session: AsyncSession) -> int:
    """Xóa dòng quá hạn lưu (12 tháng) – chạy bởi job hằng ngày."""
    result = await session.execute(
        text(f"DELETE FROM audit_log WHERE at < now() - interval '{RETENTION}'")
    )
    await session.commit()
    return result.rowcount or 0
