"""Đơn online đang chờ thanh toán của một SĐT: chặn đặt mới (E-WEB-4) + thẻ "Chờ thanh toán".

Mỗi SĐT chỉ một lượt ``pending`` (unique một phần ``uq_checkout_pending_phone``, áp chung sân +
vé). Khi bị chặn, trả kèm tóm tắt đơn cũ + ``pay_token`` để khách thanh toán hoặc hủy đơn đó.
Quá ``expires_at`` là hết là đơn chờ (ân hạn 60 giây chỉ dành cho việc ghi tiền): đặt mới gặp lượt
quá hạn mà worker chưa đóng -> đóng ngay như worker rồi cho đặt.
"""

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.booking_engine import outbox
from app.modules.booking_engine.common import Ctx, context, recover_token
from app.modules.booking_engine.dto import PendingCheckout, PendingSlot
from app.modules.booking_engine.models import Allocation, Checkout, EventSession, Hold, Resource

PENDING_MESSAGE = "Bạn còn đơn chưa thanh toán. Hãy thanh toán hoặc hủy đơn đó để đặt đơn mới."


async def _court_span(session: AsyncSession, checkout: Checkout) -> tuple[str, list]:
    """(Tên các sân theo thứ tự mã con, danh sách (tên sân, bắt đầu, kết thúc)) của lượt đặt sân."""
    rows = (
        await session.execute(
            select(Resource.name, Allocation.time_range)
            .join(Hold, Hold.id == Allocation.hold_id)
            .join(Resource, Resource.id == Allocation.resource_id)
            .where(Hold.checkout_id == checkout.id)
            .order_by(Hold.code)
        )
    ).all()
    names = list(dict.fromkeys(name for name, _ in rows))
    return ", ".join(names), [(name, r.lower, r.upper) for name, r in rows]


async def summary(session: AsyncSession, ctx: Ctx, checkout: Checkout) -> PendingCheckout:
    """Tóm tắt một lượt đang chờ: sân / sự kiện, giờ, hạn, tiền, token trang thanh toán."""
    if checkout.kind == "ticket":
        ev = await session.scalar(
            select(EventSession)
            .join(Hold, Hold.session_id == EventSession.id)
            .where(Hold.checkout_id == checkout.id)
        )
        if ev is None:  # bất biến: lượt mua vé có đúng một hold seat
            raise RuntimeError(f"Ticket checkout {checkout.order_code} has no event")
        title, spans = ev.name, [(None, ev.start_at, ev.end_at)]
    else:
        title, spans = await _court_span(session, checkout)
    day = checkout.play_date
    return PendingCheckout(
        order_code=checkout.order_code,
        kind=checkout.kind,
        title=title,
        play_date=day,
        start_time=ctx.hhmm(day, min(s for _, s, _ in spans)) if spans else "",
        end_time=ctx.hhmm(day, max(e for _, _, e in spans)) if spans else "",
        expires_at=checkout.expires_at,
        server_now=ctx.now,
        amount=checkout.amount,
        paid_amount=checkout.paid_amount,
        pay_token=recover_token(checkout.id, checkout.token_hash),
        slots=[
            PendingSlot(resource_name=n, start_time=ctx.hhmm(day, s), end_time=ctx.hhmm(day, e))
            for n, s, e in spans
            if n is not None
        ],
    )


async def pending_of_phone(session: AsyncSession, ctx: Ctx, phone: str) -> PendingCheckout | None:
    """Lượt đang chờ còn hạn của SĐT (quá ``expires_at`` không tính); không có -> None."""
    checkout = await session.scalar(
        select(Checkout).where(
            Checkout.tenant_id == ctx.tenant.id,
            Checkout.customer_phone == phone,
            Checkout.status == "pending",
            Checkout.expires_at > ctx.now,
        )
    )
    return await summary(session, ctx, checkout) if checkout else None


async def pending_for_phone(
    session: AsyncSession, tenant_id: int, phone: str
) -> PendingCheckout | None:
    return await pending_of_phone(session, await context(session, tenant_id), phone)


async def pending_error(session: AsyncSession, ctx: Ctx, phone: str) -> AppError:
    """409 E-WEB-4 kèm ``pending`` (đơn cũ) – FE dẫn khách về trang thanh toán / hủy đơn đó."""
    pending = await pending_of_phone(session, ctx, phone)
    return AppError(
        "E-WEB-4",
        PENDING_MESSAGE,
        409,
        pending=pending.model_dump(mode="json") if pending else None,
    )


async def _expire_now(session: AsyncSession, checkout: Checkout) -> None:
    """Đóng lượt quá hạn (đã khóa) đúng như worker ``expire_holds``: lượt + hold -> ``expired``,
    tắt allocation (cùng transaction). Đã nhận một phần tiền -> ``checkout.expired`` (cần hoàn)."""
    checkout.status = "expired"
    hold_ids = list(
        await session.scalars(
            update(Hold)
            .where(Hold.checkout_id == checkout.id, Hold.status == "active")
            .values(status="expired")
            .returning(Hold.id)
        )
    )
    if hold_ids:
        await session.execute(
            update(Allocation)
            .where(Allocation.hold_id.in_(hold_ids), Allocation.active)
            .values(active=False)
        )
    if checkout.paid_amount > 0:
        outbox.add_event(
            session,
            checkout.tenant_id,
            "checkout.expired",
            {"pay_ref": checkout.pay_ref, "paid_amount": checkout.paid_amount},
        )
    await session.flush()


async def raise_if_pending(session: AsyncSession, ctx: Ctx, phone: str) -> None:
    """Chặn đặt mới khi SĐT còn lượt chờ còn hạn; lượt đã quá ``expires_at`` (worker chưa chạy,
    kể cả trong ân hạn) -> đóng ngay rồi cho đặt. Khóa dòng như webhook / worker."""
    checkout = await session.scalar(
        select(Checkout)
        .where(
            Checkout.tenant_id == ctx.tenant.id,
            Checkout.customer_phone == phone,
            Checkout.status == "pending",
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if checkout is None:
        return
    if checkout.expires_at <= ctx.now:
        await _expire_now(session, checkout)
        return
    raise await pending_error(session, ctx, phone)
