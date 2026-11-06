"""Danh sách đơn đặt sân (T-039 → T-041) – chỉ đọc. Không gồm vé sự kiện, không gồm lượt giữ chỗ
online chưa trả tiền (chưa thành đơn).

Không lưu thêm lịch lúc tạo: thứ / giờ / khoảng ngày **suy từ các buổi / khối** của đơn. Trạng thái
đơn tính từ trạng thái thanh toán các khối (T-039 AC7).

T-051: tổng, số khối, giảm giá, trạng thái chỉ tính khối **chưa hủy**. Hủy hết -> ``cancelled``;
lịch
và sân lúc đó lấy theo mọi khối để dòng vẫn đọc được.
"""

import re
from collections import defaultdict
from datetime import date

from sqlalchemy import Integer, case, cast, distinct, exists, func, or_, select
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.booking_engine.common import context
from app.modules.booking_engine.dto import (
    OrderCounts,
    OrderKind,
    OrderList,
    OrderRow,
    RecurringCounts,
    RecurringOrderList,
    RecurringOrderRow,
    RecurringStatus,
)
from app.modules.booking_engine.models import Booking, BookingOrder, Resource

MAX_SIZE = 50
STATUSES: tuple[RecurringStatus, ...] = ("unpaid", "paid", "uncollectible", "cancelled")


def _like(text: str) -> str:
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def _counts(rows: dict[str, int]) -> RecurringCounts:
    return RecurringCounts(all=sum(rows.values()), **{s: rows.get(s, 0) for s in STATUSES})


async def list_all(
    session: AsyncSession,
    tenant_id: int,
    *,
    kind: OrderKind | None = None,
    status: RecurringStatus | None = None,
    q: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = 1,
    size: int = 20,
) -> OrderList:
    """Đơn đặt sân mới nhất trước. ``date_from`` / ``date_to``: đơn có khối chơi trong khoảng.

    ``counts`` theo loại × trạng thái, tính theo ``q`` + khoảng ngày (bỏ qua ``kind`` / ``status``).
    """
    ctx = await context(session, tenant_id)
    size = max(1, min(size, MAX_SIZE))
    page = max(1, page)
    unpaid = func.count().filter(Booking.payment_status == "unpaid")
    uncollectible = func.count().filter(Booking.payment_status == "uncollectible")
    weekday = cast(func.extract("isodow", Booking.play_date), Integer)
    live = Booking.payment_status != "cancelled"
    live_blocks = func.count().filter(live)
    weekdays = func.array_agg(aggregate_order_by(distinct(weekday), weekday))

    def live_or_all(agg_fn, column):
        return func.coalesce(agg_fn(column).filter(live), agg_fn(column))

    agg = (
        select(
            Booking.order_id.label("order_id"),
            live_blocks.label("blocks"),
            func.coalesce(func.sum(Booking.amount).filter(live), 0).label("total"),
            func.coalesce(
                func.sum(func.coalesce(Booking.list_amount, Booking.amount)).filter(live), 0
            ).label("original"),
            live_or_all(func.min, Booking.play_date).label("date_from"),
            live_or_all(func.max, Booking.play_date).label("date_to"),
            live_or_all(func.min, Booking.start_at).label("first_start"),
            live_or_all(func.min, Booking.end_at).label("first_end"),
            func.coalesce(weekdays.filter(live), weekdays).label("weekdays"),
            case(
                (live_blocks == 0, "cancelled"),
                (unpaid > 0, "unpaid"),
                (uncollectible > 0, "uncollectible"),
                else_="paid",
            ).label("status"),
        )
        .where(Booking.tenant_id == tenant_id)
        .group_by(Booking.order_id)
        .subquery()
    )
    conds = [BookingOrder.tenant_id == tenant_id]
    text = (q or "").strip()
    if text:
        code = _like(text.replace(" ", "").upper())
        found = [
            BookingOrder.code.ilike(code),
            exists().where(Booking.order_id == BookingOrder.id, Booking.code.ilike(code)),
            BookingOrder.customer_name.ilike(_like(text)),
        ]
        digits = re.sub(r"[\s.]", "", text)
        if digits.isdigit():
            found.append(BookingOrder.customer_phone.like(_like(digits)))
        conds.append(or_(*found))
    if date_from is not None:
        conds.append(agg.c.date_to >= date_from)
    if date_to is not None:
        conds.append(agg.c.date_from <= date_to)

    count_rows = await session.execute(
        select(BookingOrder.kind, agg.c.status, func.count())
        .select_from(BookingOrder)
        .join(agg, agg.c.order_id == BookingOrder.id)
        .where(*conds)
        .group_by(BookingOrder.kind, agg.c.status)
    )
    by_kind: dict[str, dict[str, int]] = defaultdict(dict)
    for k, s, n in count_rows:
        by_kind[k][s] = n
    every: dict[str, int] = defaultdict(int)
    for rows in by_kind.values():
        for s, n in rows.items():
            every[s] += n
    counts = OrderCounts(
        all=_counts(every),
        single=_counts(by_kind.get("single", {})),
        recurring=_counts(by_kind.get("recurring", {})),
    )

    page_conds = list(conds)
    if kind is not None:
        page_conds.append(BookingOrder.kind == kind)
    if status is not None:
        page_conds.append(agg.c.status == status)
    rows = (
        await session.execute(
            select(BookingOrder, agg)
            .join(agg, agg.c.order_id == BookingOrder.id)
            .where(*page_conds)
            .order_by(BookingOrder.created_at.desc(), BookingOrder.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    ).all()

    # Sân của từng đơn (đơn ngày có thể nhiều sân), theo thứ tự hiển thị
    courts: dict[int, list[tuple[str, str]]] = defaultdict(list)
    live_courts: dict[int, list[tuple[str, str]]] = defaultdict(list)
    if rows:
        for order_id, rcode, rname, is_live in await session.execute(
            select(Booking.order_id, Resource.code, Resource.name, live)
            .join(Resource, Resource.id == Booking.resource_id)
            .where(Booking.order_id.in_([r[0].id for r in rows]))
            .distinct()
            .order_by(Booking.order_id, Resource.code)
        ):
            if (rcode, rname) not in courts[order_id]:
                courts[order_id].append((rcode, rname))
            if is_live:
                live_courts[order_id].append((rcode, rname))

    items = []
    for order, *values in rows:
        a = dict(zip(agg.c.keys(), values, strict=True))
        first_day = a["date_from"]
        here = live_courts.get(order.id) or courts.get(order.id) or [("", "")]
        items.append(
            OrderRow(
                order_code=order.code,
                kind=order.kind,  # type: ignore[arg-type]
                source=order.channel,  # type: ignore[arg-type]
                customer_name=order.customer_name,
                customer_phone=order.customer_phone,
                member_code=order.member_code if order.customer_kind == "member" else None,
                resource_code=here[0][0],
                resource_name=here[0][1],
                resource_codes=[c for c, _ in here],
                resource_names=[n for _, n in here],
                play_date=order.play_date,
                weekdays=[int(w) for w in a["weekdays"]],
                start_hour=ctx.minute_of(first_day, a["first_start"]) // 60,
                end_hour=ctx.minute_of(first_day, a["first_end"]) // 60,
                date_from=first_day,
                date_to=a["date_to"],
                sessions=a["blocks"],
                blocks=a["blocks"],
                original_amount=int(a["original"]),
                discount_pct=order.discount_pct or 0,
                # Từ các khối chưa hủy; cột lưu trên booking_order không đổi khi hủy
                discount_amount=int(a["original"]) - int(a["total"]),
                total=int(a["total"]),
                status=a["status"],
                created_at=order.created_at,
                created_by=order.created_by_label,
            )
        )
    scope = counts.all if kind is None else getattr(counts, kind)
    total = scope.all if status is None else getattr(scope, status)
    return OrderList(items=items, counts=counts, page=page, size=size, total=total)


async def list_orders(
    session: AsyncSession,
    tenant_id: int,
    status: RecurringStatus | None,
    q: str | None,
    page: int,
    size: int,
) -> RecurringOrderList:
    """Chỉ đơn định kỳ (T-039, giữ cho ``/front-desk/recurring``)."""
    out = await list_all(
        session, tenant_id, kind="recurring", status=status, q=q, page=page, size=size
    )
    fields = set(RecurringOrderRow.model_fields)
    return RecurringOrderList(
        items=[RecurringOrderRow(**r.model_dump(include=fields)) for r in out.items],
        counts=out.counts.recurring,
        page=out.page,
        size=out.size,
        total=out.total,
    )
