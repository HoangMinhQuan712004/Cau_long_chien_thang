"""Giữ chỗ online (BR-002, 5 phút): hết hạn -> ``expired`` + trả khung (tắt allocation).

Giữ chỗ của một lượt thanh toán (checkout, ADR-007) được thêm **ân hạn**
``ONLINE_HOLD_GRACE_SECONDS`` (60 giây) để nhận tiền báo trễ: trong ân hạn khung vẫn bị chiếm.
Checkout hết hạn mà đã nhận một phần tiền -> phát ``checkout.expired`` để module thanh toán đánh
dấu các giao dịch đó cần hoàn (T-008 AC22).
"""

from datetime import datetime, timedelta

from sqlalchemy import and_, or_, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.booking_engine import outbox
from app.modules.booking_engine.models import Hold

_EXPIRE_CHECKOUTS = text(
    """
    UPDATE booking.checkout SET status = 'expired', updated_at = now()
    WHERE status = 'pending' AND expires_at <= now() - make_interval(secs => :grace)
    RETURNING id, tenant_id, pay_ref, paid_amount
    """
)

# Một câu lệnh: hết hạn giữ chỗ (không thuộc checkout: quá expires_at; thuộc checkout: checkout
# vừa hết hạn) và tắt allocation của chúng
_EXPIRE_HOLDS = text(
    """
    WITH expired AS (
        UPDATE booking.hold SET status = 'expired'
        WHERE status = 'active' AND (
            (checkout_id IS NULL AND expires_at <= now())
            OR checkout_id = ANY(CAST(:checkout_ids AS uuid[]))
        )
        RETURNING id
    ), freed AS (
        UPDATE booking.allocation a SET active = false
        FROM expired e
        WHERE a.hold_id = e.id AND a.active
        RETURNING a.id
    )
    SELECT (SELECT count(*) FROM expired) AS holds
    """
)


def grace() -> timedelta:
    return timedelta(seconds=settings.ONLINE_HOLD_GRACE_SECONDS)


def hold_visible(now: datetime):
    """Điều kiện SQL: giữ chỗ còn chiếm khung lúc ``now`` (kể cả trong ân hạn của checkout)."""
    return and_(
        Hold.status == "active",
        or_(
            and_(Hold.checkout_id.is_(None), Hold.expires_at > now),
            and_(Hold.checkout_id.isnot(None), Hold.expires_at > now - grace()),
        ),
    )


async def expire_holds(session: AsyncSession) -> int:
    """Hết hạn giữ chỗ / checkout quá giờ (không commit). Trả số giữ chỗ vừa hết hạn.

    Worker gọi mỗi 30 giây; thao tác đặt cũng gọi trước khi chiếm khung để giữ chỗ vừa hết
    hạn không chặn lượt đặt mới. Khóa dòng checkout giống lúc nhận tiền -> không đua với webhook.
    """
    checkouts = (
        await session.execute(_EXPIRE_CHECKOUTS, {"grace": settings.ONLINE_HOLD_GRACE_SECONDS})
    ).all()
    row = (
        await session.execute(_EXPIRE_HOLDS, {"checkout_ids": [str(c.id) for c in checkouts]})
    ).one()
    for c in checkouts:
        if c.paid_amount > 0:
            outbox.add_event(
                session,
                c.tenant_id,
                "checkout.expired",
                {"pay_ref": c.pay_ref, "paid_amount": c.paid_amount},
            )
    return int(row.holds)
