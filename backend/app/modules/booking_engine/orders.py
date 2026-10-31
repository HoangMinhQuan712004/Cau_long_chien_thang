"""Đơn đặt – mã chung cho một lượt đặt (T-019, ADR-010).

Một checkout online đã thanh toán, hoặc một lần bấm Đặt sân ở quầy = **một đơn** mã
``BK-YYYYMMDD-NNN``; mỗi khối (booking) mang mã con ``{mã đơn}-NN`` (01–99), đánh số theo sân rồi
giờ bắt đầu. Giá, thanh toán, Không thu được và chống trùng lịch vẫn theo từng khối.
Hàm ở đây **không commit**.
"""

import re
import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit, audit_detail
from app.core.errors import AppError
from app.modules.booking_engine import outbox
from app.modules.booking_engine.audit_fields import paid_changes
from app.modules.booking_engine.common import Ctx, audit_actor, context
from app.modules.booking_engine.dto import (
    Actor,
    CustomerSnapshot,
    OrderCollectIn,
    OrderCollectOut,
)
from app.modules.booking_engine.models import Allocation, Booking, BookingOrder, Resource

CHILD_RE = re.compile(r"^(?P<order>.+)-(?P<seq>\d{2})$")
MAX_BLOCKS = 99


def child_code(order_code: str, seq: int) -> str:
    return f"{order_code}-{seq:02d}"


def order_of_child(code: str) -> str | None:
    """``BK-20261030-003-02`` -> ``BK-20261030-003``; mã đơn / mã khác -> None."""
    m = CHILD_RE.match(code)
    return m.group("order") if m else None


def ranges_of(hours: list[int]) -> list[tuple[int, int]]:
    """[19, 20, 22] -> [(19, 21), (22, 23)]."""
    result: list[list[int]] = []
    for h in sorted(set(hours)):
        if result and result[-1][1] == h:
            result[-1][1] = h + 1
        else:
            result.append([h, h + 1])
    return [(a, b) for a, b in result]


async def conflicts_of(
    session: AsyncSession, ctx: Ctx, day: date, ranges: list[tuple[Resource, int, int]]
) -> list[dict]:
    """Ô nào đang bị chiếm (409 kèm ``conflicts`` – online E-WEB-3, quầy E-003)."""
    result = []
    for r, a, b in ranges:
        for h in range(a, b):
            taken = await session.scalar(
                select(Allocation.id)
                .where(
                    Allocation.tenant_id == ctx.tenant.id,
                    Allocation.resource_id == r.id,
                    Allocation.active.is_(True),
                    Allocation.time_range.overlaps(
                        Range(ctx.at(day, h * 60), ctx.at(day, h * 60 + 60), bounds="[)")
                    ),
                )
                .limit(1)
            )
            if taken is not None:
                result.append({"resource_code": r.code, "start_hour": h})
    return result


def order_not_found() -> AppError:
    return AppError("E-BOOK-3", "Không tìm thấy mã đặt.", 404)


def snapshot_values(customer: CustomerSnapshot) -> dict:
    return {
        "customer_ref": customer.ref_id,
        "customer_kind": customer.kind,
        "customer_name": customer.display_name,
        "customer_phone": customer.phone,
        "member_code": customer.member_code,
        "member_tier": customer.tier,
    }


def new_order(
    tenant_id: int,
    code: str,
    play_date: date,
    channel: str,
    snapshot: dict,
    created_by_label: str,
    checkout_id: uuid.UUID | None = None,
) -> BookingOrder:
    return BookingOrder(
        tenant_id=tenant_id,
        code=code,
        play_date=play_date,
        channel=channel,
        checkout_id=checkout_id,
        created_by_label=created_by_label,
        **snapshot,
    )


async def find_order(session: AsyncSession, tenant_id: int, code: str) -> BookingOrder | None:
    """Đơn theo mã đơn **hoặc** mã con (AC3, AC4)."""
    order = await session.scalar(
        select(BookingOrder).where(BookingOrder.tenant_id == tenant_id, BookingOrder.code == code)
    )
    if order is not None:
        return order
    b = await session.scalar(
        select(Booking).where(Booking.tenant_id == tenant_id, Booking.code == code)
    )
    return await session.get(BookingOrder, b.order_id) if b is not None else None


async def order_blocks(session: AsyncSession, order_id: int, lock: bool = False) -> list[Booking]:
    q = select(Booking).where(Booking.order_id == order_id).order_by(Booking.seq)
    if lock:
        q = q.with_for_update()
    return list(await session.scalars(q))


async def order_codes(session: AsyncSession, order_ids: set[int]) -> dict[int, str]:
    """``order_id -> mã đơn`` cho một loạt khối (lịch, lịch sử giao dịch)."""
    if not order_ids:
        return {}
    rows = await session.execute(
        select(BookingOrder.id, BookingOrder.code).where(BookingOrder.id.in_(order_ids))
    )
    return {order_id: code for order_id, code in rows}


async def collect_order(
    session: AsyncSession, tenant_id: int, actor: Actor, raw_code: str, data: OrderCollectIn
) -> OrderCollectOut:
    """Thu cả đơn: mọi khối **Chưa thanh toán** của đơn -> Đã thanh toán (tiền mặt), khóa dòng.

    Khối đã thu / Không thu được giữ nguyên. Không còn khối nào chưa thu -> 409 ``E-BOOK-4``.
    """
    from app.modules.booking_engine.booking_service import booking_item, normalize_code
    from app.modules.booking_engine.payment_service import cash_only, mark_paid

    cash_only(data)
    code = normalize_code(raw_code)
    order = await session.scalar(
        select(BookingOrder).where(BookingOrder.tenant_id == tenant_id, BookingOrder.code == code)
    )
    if order is None:
        raise order_not_found()
    ctx: Ctx = await context(session, tenant_id)
    blocks = await order_blocks(session, order.id, lock=True)
    unpaid = [b for b in blocks if b.payment_status == "unpaid"]
    if not unpaid:
        raise AppError("E-BOOK-4", "Đơn không còn khối nào chưa thanh toán.", 409)
    for b in unpaid:
        mark_paid(session, ctx, tenant_id, actor, b)
    # Dòng tổng của cả đơn (màn Lịch sử thao tác hiện từng khối ``payment.collect`` ở trên)
    audit(
        session,
        audit_actor(actor),
        "payment.collect_order",
        "booking_order",
        order.code,
        audit_detail(
            order.code,
            unpaid[0].customer_name,
            paid_changes("Tiền mặt"),
            codes=[b.code for b in unpaid],
            amount=sum(b.amount for b in unpaid),
            method="cash",
        ),
    )
    await session.flush()
    items = []
    for b in blocks:
        await session.refresh(b)
        items.append(await booking_item(session, ctx, b))
    return OrderCollectOut(
        order_code=order.code,
        collected=[b.code for b in unpaid],
        amount=sum(b.amount for b in unpaid),
        bookings=items,
    )


def emit_created(
    session: AsyncSession, tenant_id: int, order: BookingOrder, block: Booking
) -> None:
    """Sự kiện ``booking.created`` cho từng khối, mang cả mã đơn (AC8; phòng chơi gắn mã con)."""
    outbox.add_event(
        session,
        tenant_id,
        "booking.created",
        {
            "code": block.code,
            "order_code": order.code,
            "source": block.source,
            "play_date": block.play_date.isoformat(),
        },
    )
