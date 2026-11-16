"""Khách / hội viên tự hủy giữ chỗ một lượt online (sân hoặc vé) khi chưa trả đồng nào.

Khóa dòng checkout (``FOR UPDATE``) như lúc nhận tiền / hết hạn -> không đua với webhook hay
worker. Cùng transaction: lượt -> ``cancelled``, hold -> ``released``, tắt allocation (khung sân
mở lại ngay; ghế sự kiện không còn được đếm). Tiền về sau khi hủy đi đường của lượt đã đóng:
``refund_needed``, lượt không sống lại. Hàm **không commit**.
"""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit
from app.core.errors import AppError
from app.modules.booking_engine import outbox
from app.modules.booking_engine.common import audit_actor, context, token_hash
from app.modules.booking_engine.dto import Actor, CheckoutView
from app.modules.booking_engine.models import Allocation, Checkout, Hold
from app.modules.booking_engine.online_service import checkout_view

_REFUSED = {
    "paid": "Đơn đã thanh toán, không thể hủy.",
    "partially_paid": "Đơn đã ghi nhận tiền chuyển khoản, không thể hủy. Vui lòng liên hệ sân.",
    "expired": "Đơn đã hết hạn giữ chỗ.",
}


def _not_found() -> AppError:
    return AppError("E-WEB-6", "Không tìm thấy lượt thanh toán.", 404)


def _refused(reason: str) -> AppError:
    return AppError("E-WEB-12", _REFUSED[reason], 409, reason=reason)


def _refusal(checkout: Checkout) -> str | None:
    """Lý do không hủy được (None: hủy được). Hết hạn mà worker chưa đóng vẫn hủy được."""
    if checkout.status == "paid":
        return "paid"
    if checkout.paid_amount > 0:
        return "partially_paid"
    if checkout.status == "expired":
        return "expired"
    return None


async def cancel_checkout(
    session: AsyncSession,
    tenant_id: int,
    token: str,
    member_refs: list[str] | None,
    actor: Actor,
) -> CheckoutView:
    """Hủy giữ chỗ theo token trang thanh toán; gọi lại khi đã hủy -> cùng kết quả.

    Lượt của hội viên chỉ chính hội viên đó (``member_refs`` chứa ``customer_ref``) hủy được;
    còn lại -> 404 như token sai. 409 E-WEB-12 (``reason``: paid / partially_paid / expired).
    """
    ctx = await context(session, tenant_id)
    if not token or len(token) > 100:
        raise _not_found()
    checkout = await session.scalar(
        select(Checkout)
        .where(Checkout.tenant_id == tenant_id, Checkout.token_hash == token_hash(token))
        .with_for_update()
    )
    if checkout is None:
        raise _not_found()
    if checkout.customer_kind == "member" and checkout.customer_ref not in (member_refs or []):
        raise _not_found()
    if checkout.status == "cancelled":
        return await checkout_view(session, ctx, checkout)
    reason = _refusal(checkout)
    if reason is not None:
        raise _refused(reason)

    hold_ids = list(
        await session.scalars(
            update(Hold)
            .where(Hold.checkout_id == checkout.id, Hold.status == "active")
            .values(status="released")
            .returning(Hold.id)
        )
    )
    if hold_ids:
        await session.execute(
            update(Allocation)
            .where(Allocation.hold_id.in_(hold_ids), Allocation.active)
            .values(active=False)
        )
    checkout.status = "cancelled"
    audit(
        session,
        audit_actor(actor),
        "checkout.cancel",
        "checkout",
        checkout.pay_ref,
        {"kind": checkout.kind, "order_code": checkout.order_code, "amount": checkout.amount},
    )
    outbox.add_event(
        session,
        tenant_id,
        "checkout.cancelled",
        {"pay_ref": checkout.pay_ref, "order_code": checkout.order_code, "kind": checkout.kind},
    )
    await session.flush()
    return await checkout_view(session, ctx, checkout)
