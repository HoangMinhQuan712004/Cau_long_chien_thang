"""Giữ chỗ online (BR-002, 5 phút): hết hạn -> ``expired`` + trả khung (tắt allocation).

Hết ``expires_at`` là khung mở lại ngay (người dùng 13/11: bỏ "Sắp mở lại"). **Ân hạn**
``ONLINE_HOLD_GRACE_SECONDS`` (60 giây) chỉ còn để nhận tiền báo trễ: worker chờ hết ân hạn mới đóng
lượt; thao tác đặt thì đóng ngay lượt đã quá hạn (``grace_seconds=0``) để khung lấy lại được.
Tiền về trong ân hạn mà khung đã bị lấy -> lượt đã ``expired`` -> cần hoàn như tiền về trễ.
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
    """Điều kiện SQL: giữ chỗ còn chiếm khung lúc ``now`` – tới đúng ``expires_at``."""
    return and_(Hold.status == "active", Hold.expires_at > now)


def seat_hold_counted(now: datetime):
    """Điều kiện SQL: ghế giữ trong sự kiện còn chiếm chỗ lúc ``now``.

    Ghế của lượt mua vé (T-023) còn tính tới khi ``expire_holds`` nhả (checkout hết hạn sau ân
    hạn): tiền về hợp lệ cho lượt còn ``pending`` luôn có ghế, quầy không bán chồng lên.
    """
    return and_(
        Hold.status == "active",
        or_(Hold.checkout_id.isnot(None), Hold.expires_at > now),
    )


async def expire_holds(session: AsyncSession, grace_seconds: int = 0) -> int:
    """Hết hạn giữ chỗ / checkout quá giờ (không commit). Trả số giữ chỗ vừa hết hạn.

    Worker gọi mỗi 30 giây với ân hạn (``ONLINE_HOLD_GRACE_SECONDS``); thao tác đặt gọi với 0
    trước khi chiếm khung để lượt vừa quá hạn không chặn lượt đặt mới. Khóa dòng checkout giống lúc
    nhận tiền -> không đua với webhook.
    """
    checkouts = (await session.execute(_EXPIRE_CHECKOUTS, {"grace": grace_seconds})).all()
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
