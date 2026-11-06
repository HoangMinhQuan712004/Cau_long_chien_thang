"""Tổng quan (AC1–AC3) và Lịch sử thanh toán (AC7–AC10) của hội viên – BFF ghép Hội viên, Phòng
chơi, Thông báo và Booking engine. Mọi dữ liệu theo hồ sơ của phiên (không IDOR)."""

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.modules.auth import api as auth
from app.modules.booking_engine import api as engine
from app.modules.member_area.home_schemas import (
    BookingSummary,
    EventCard,
    Overview,
    OverviewRanking,
    OverviewRankingMe,
    PaymentItem,
    PaymentList,
    PaymentSummary,
    RecentRecord,
    TicketSummary,
    UpcomingItem,
)
from app.modules.member_inbox import api as inbox
from app.modules.members import api as members
from app.modules.payments import api as payments_api
from app.modules.play_rooms import api as rooms
from app.modules.records import api as records

UPCOMING_MAX = 4
EVENT_DAYS = 14
EVENTS_MAX = 3
OPEN_ROOMS_MAX = 3
RECENT_RECORDS_MAX = 3
TOP = 10
MONTHS_MAX = 12


def short_name(full_name: str) -> str:
    words = full_name.split()
    return words[-1] if words else full_name


def _local(t: dt.datetime) -> dt.datetime:
    return t.astimezone(settings.tz)


def _hm(t: dt.datetime) -> str:
    local = _local(t)
    return f"{local.hour}h" if local.minute == 0 else f"{local.hour}h{local.minute:02d}"


def not_member() -> AppError:
    return AppError("E-HV-8", "Bạn chưa là hội viên.", 403)


# ------------------------------------------------------------------ Tổng quan


async def overview(session: AsyncSession, customer_id: int, user_id: int) -> Overview:
    profile = await members.get_self_profile(session, customer_id)
    if profile is None:
        raise not_member()
    now = dt.datetime.now(dt.UTC)
    today = _local(now).date()

    items: list[UpcomingItem] = [
        UpcomingItem(
            room_id=r.room_id,
            booking_code=r.booking_code,
            order_code=None,
            play_date=_local(r.start_at).date(),
            start_at=r.start_at,
            end_at=r.end_at,
            phase="ongoing" if r.start_at <= now else "upcoming",
            resource_name=r.resource_name,
            resource_type_name=r.resource_type_name,
            role=r.role,  # type: ignore[arg-type]
            host_name=r.host_name,
            members_preview=r.members_preview,
            count=r.count,
            capacity=r.capacity,
        )
        for r in await rooms.my_rooms(session, customer_id)
        if r.end_at > now
    ]
    # Booking của mình chưa có phòng (đặt trước khi có phòng chơi / ``phone:…``) – Q1 chốt 01/11
    refs = await members.booking_refs_of(session, customer_id)
    bookings = await engine.upcoming_bookings(session, refs, now)
    with_room = await rooms.booking_codes_with_room(session, [b.code for b in bookings])
    order_of = {b.code: b.order_code for b in bookings}
    me = profile.nickname or profile.full_name
    for b in bookings:
        if b.code in with_room:
            continue
        items.append(
            UpcomingItem(
                room_id=None,
                booking_code=b.code,
                order_code=b.order_code,
                play_date=b.play_date,
                start_at=b.start_at,
                end_at=b.end_at,
                phase="ongoing" if b.start_at <= now else "upcoming",
                resource_name=b.resource_name,
                resource_type_name=b.resource_type_name,
                role="host",
                host_name=me,
                members_preview=[],
                count=None,
                capacity=None,
            )
        )
    for item in items:
        if item.order_code is None:
            item.order_code = order_of.get(item.booking_code)
    items.sort(key=lambda i: (i.start_at, i.resource_name, i.booking_code))
    month = _ym(today)
    return Overview(
        greeting_name=profile.nickname or short_name(profile.full_name),
        today=today,
        today_count=sum(_local(i.start_at).date() == today for i in items),
        upcoming=items[:UPCOMING_MAX],
        unread_count=await inbox.unread_count(session, customer_id),
        month=month,
        month_stats=await rooms.month_stats(session, customer_id, month),
        month_record_kmh=await records.month_best(session, customer_id, today),
        record_kmh=await records.record_kmh(session, customer_id),
        open_rooms=await rooms.open_rooms_today(session, user_id, customer_id, OPEN_ROOMS_MAX),
        ranking=await _ranking(session, customer_id, today),
        recent_records=await _recent_records(session, customer_id),
        upcoming_events=(await events(session, customer_id, EVENT_DAYS))[:EVENTS_MAX],
    )


async def _ranking(session: AsyncSession, customer_id: int, today: dt.date) -> OverviewRanking:
    r = await records.speed_ranking(session, customer_id, "month", today)
    top10 = r.top[TOP - 1].speed_kmh if len(r.top) >= TOP else None
    me = (
        OverviewRankingMe(
            rank=r.me.rank,
            speed_kmh=r.me.speed_kmh,
            gap_to_top10=r.me.gap_to_top10,
            top10_kmh=top10,
        )
        if r.me
        else None
    )
    return OverviewRanking(
        total_members=r.total_members, total_records=r.total_records, me=me, top3=r.top[:3]
    )


async def _recent_records(session: AsyncSession, customer_id: int) -> list[RecentRecord]:
    """3 lần phá kỷ lục cụm gần nhất; sân đổi từ mã qua engine, vợt chỉ khi người đó hiện tên."""
    breaks = await records.club_record_breaks(session, customer_id, RECENT_RECORDS_MAX)
    if not breaks:
        return []
    names = {r.code: r.name for r in (await engine.list_resources(session)).items}
    rackets = await members.rackets_of(session, {b.customer_id for b in breaks if b.shown})
    return [
        RecentRecord(
            speed_kmh=b.speed_kmh,
            delta_kmh=b.delta_kmh,
            display_name=b.display_name,
            avatar_url=b.avatar_url,
            racket=rackets.get(b.customer_id) if b.shown else None,
            resource_name=names.get(b.court_code) if b.court_code else None,
            measured_at=b.measured_at,
            is_current=b.is_current,
            video=records.video_of(b.video_url),
        )
        for b in breaks
    ]


# ------------------------------------------------------------------ Lịch sử thanh toán


def _month_start(year: int, month: int) -> dt.datetime:
    return dt.datetime(year, month, 1, tzinfo=settings.tz)


def _next_month(start: dt.datetime) -> dt.datetime:
    return _month_start(start.year + start.month // 12, start.month % 12 + 1)


def parse_month(value: str | None) -> dt.datetime:
    """``YYYY-MM`` -> đầu tháng (giờ VN); None -> tháng hiện tại; sai -> 422 E-WEB-1."""
    if value is None:
        now = _local(dt.datetime.now(dt.UTC))
        return _month_start(now.year, now.month)
    try:
        year, month = (int(p) for p in value.split("-"))
        return _month_start(year, month)
    except ValueError:
        raise AppError("E-WEB-1", "Tháng không hợp lệ (YYYY-MM).", 422) from None


def _ym(t: dt.datetime | dt.date) -> str:
    return f"{t.year:04d}-{t.month:02d}"


def _item(p: engine.PaidItem) -> PaymentItem:
    time = f"{_hm(p.start_at)}–{_hm(p.end_at)}"
    if p.kind == "booking":
        title = f"Đặt sân · {', '.join(p.resource_names)} · {time}"
        display = p.order_code or p.code
    else:
        title = " · ".join(
            x for x in ("Vé sự kiện", p.event_name or "", ", ".join(p.resource_names)) if x
        )
        display = p.code
    return PaymentItem(
        kind=p.kind,
        code=p.code,
        display_code=display,
        title=title,
        event_name=p.event_name,
        resource_names=p.resource_names,
        play_date=p.play_date,
        start_at=p.start_at,
        end_at=p.end_at,
        amount=p.amount,
        paid_at=p.paid_at,
        method="Tiền mặt" if p.payment_method == "cash" else "QR",
        channel=p.channel,
        cancelled=p.cancelled,
        refund_amount=p.refund_amount,
    )


async def payments(
    session: AsyncSession, customer_id: int, month: str | None, kind: str
) -> PaymentList:
    start = parse_month(month)
    end = _next_month(start)
    refs = await members.booking_refs_of(session, customer_id)
    paid = [_item(p) for p in await engine.paid_items(session, refs, start, end)]

    current = _local(dt.datetime.now(dt.UTC))
    months = {_ym(current)} | {
        _ym(m)
        for m in await engine.paid_months(
            session, refs, dt.datetime(2000, 1, 1, tzinfo=dt.UTC), settings.tz
        )
    }
    kept = [p for p in paid if not p.cancelled]  # đã hủy vẫn hiện nhưng không cộng vào tổng
    bookings = [p for p in kept if p.kind == "booking"]
    tickets = [p for p in kept if p.kind == "ticket"]
    hours = sum((p.end_at - p.start_at).total_seconds() for p in bookings) / 3600
    return PaymentList(
        month=_ym(start),
        months=sorted(months, reverse=True)[:MONTHS_MAX],
        summary=PaymentSummary(
            total=sum(p.amount for p in kept),
            count=len(kept),
            bookings=BookingSummary(count=len(bookings), hours=round(hours, 2)),
            tickets=TicketSummary(count=len(tickets), total=sum(p.amount for p in tickets)),
        ),
        items=[p for p in paid if kind == "all" or p.kind == kind],
    )


async def payment(session: AsyncSession, customer_id: int, code: str) -> PaymentItem:
    """Chi tiết một khoản đã thanh toán của chính mình; khác -> 404."""
    refs = await members.booking_refs_of(session, customer_id)
    found = await engine.paid_item(session, refs, code)
    if found is None:
        raise AppError("E-NOT-FOUND", "Không tìm thấy khoản thanh toán.", 404)
    return _item(found)


# ------------------------------------------------------------------ Sự kiện sắp tới (T-045)


async def events(session: AsyncSession, customer_id: int, days: int) -> list[EventCard]:
    """Sự kiện chưa bắt đầu trong ``days`` ngày tới, có "vé của tôi". Đặt online tắt -> nút mờ với
    lý do ``online_off`` (cùng điều kiện ``/web/booking/events/{code}``)."""
    refs = await members.booking_refs_of(session, customer_id)
    found = await engine.upcoming_events(session, refs, days)
    if not found:
        return []
    online = auth.otp_channel_ready() and await payments_api.online_enabled(session)
    out = []
    for e in found:
        card = EventCard(**e.model_dump())
        if card.can_buy and not online:
            card.can_buy, card.reason = False, "online_off"
        out.append(card)
    return out
