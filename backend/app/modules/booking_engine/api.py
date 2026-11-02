"""MẶT TIỀN DUY NHẤT của booking engine (ADR-003).

Module khác (và router HTTP của engine) chỉ gọi các hàm ở đây, vào/ra bằng DTO (``dto.py``).

Quy ước transaction: hàm ghi **không commit** – người gọi sở hữu transaction (router commit qua
``Idempotency.run``; BFF có thể gộp thao tác của nhiều module trong cùng một transaction).
``tenant_id`` mặc định là tenant của bản chạy (``TENANT_ID``).
"""

import datetime as dt
from zoneinfo import ZoneInfo

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.booking_engine import (
    booking_service,
    config_service,
    customer_history,
    holds,
    member_history,
    online_service,
    orders,
    outbox,
    payment_service,
    report_figures,
    rooms_feed,
    session_service,
    ticket_online,
    transactions,
)
from app.modules.booking_engine import member_calendar as member_cal
from app.modules.booking_engine.dto import (
    Actor,
    CalendarOut,
    CheckoutCreate,
    CheckoutCreated,
    CheckoutView,
    CollectIn,
    CounterOrderIn,
    CounterOrderOut,
    CustomerBookingRow,
    CustomerSnapshot,
    CustomerStats,
    EventInfo,
    ItemOut,
    LookupResult,
    MemberCalendar,
    MemberOrder,
    OnlinePaymentIn,
    OnlinePaymentResult,
    OrderCollectIn,
    OrderCollectOut,
    PaidItem,
    PriceTable,
    PriceTableUpdate,
    PublicCalendar,
    PublicPrices,
    QuoteIn,
    QuoteOut,
    ReportFigures,
    ResourceCreate,
    ResourceList,
    ResourceOut,
    ResourceUpdate,
    RoomSource,
    SearchResult,
    SessionCreate,
    SessionOut,
    SpecialDayIn,
    SpecialDayOut,
    TransactionsOut,
    TransactionsQuery,
    UncollectibleIn,
    UpcomingBooking,
)
from app.modules.booking_engine.models import DEFAULT_TENANT_SETTINGS, Tenant
from app.modules.booking_engine.tenant import current_tenant_id


def _tid(tenant_id: int | None) -> int:
    return current_tenant_id() if tenant_id is None else tenant_id


# ---- Tài nguyên


async def list_resources(session: AsyncSession, *, tenant_id: int | None = None) -> ResourceList:
    return await config_service.list_resources(session, _tid(tenant_id))


async def create_resource(
    session: AsyncSession, actor: Actor, data: ResourceCreate, *, tenant_id: int | None = None
) -> ResourceOut:
    return await config_service.create_resource(session, _tid(tenant_id), actor, data)


async def update_resource(
    session: AsyncSession,
    actor: Actor,
    code: str,
    data: ResourceUpdate,
    *,
    tenant_id: int | None = None,
) -> ResourceOut:
    return await config_service.update_resource(session, _tid(tenant_id), actor, code, data)


async def upsert_resource_type(
    session: AsyncSession, code: str, name: str, sort: int = 0, *, tenant_id: int | None = None
) -> None:
    await config_service.upsert_resource_type(session, _tid(tenant_id), code, name, sort)


# ---- Bảng giá


async def get_price_table(session: AsyncSession, *, tenant_id: int | None = None) -> PriceTable:
    return await config_service.get_price_table(session, _tid(tenant_id))


async def update_price_table(
    session: AsyncSession, actor: Actor, data: PriceTableUpdate, *, tenant_id: int | None = None
) -> PriceTable:
    return await config_service.update_price_table(session, _tid(tenant_id), actor, data)


async def public_prices(session: AsyncSession, *, tenant_id: int | None = None) -> PublicPrices:
    """Bảng giá rút gọn cho trang public (không cần đăng nhập)."""
    return await config_service.public_prices(session, _tid(tenant_id))


# ---- Ngày Lễ / Tết


async def list_special_days(
    session: AsyncSession, year: int | None = None, *, tenant_id: int | None = None
) -> list[SpecialDayOut]:
    return await config_service.list_special_days(session, _tid(tenant_id), year)


async def create_special_day(
    session: AsyncSession, actor: Actor, data: SpecialDayIn, *, tenant_id: int | None = None
) -> SpecialDayOut:
    return await config_service.create_special_day(session, _tid(tenant_id), actor, data)


async def delete_special_day(
    session: AsyncSession, actor: Actor, special_day_id: int, *, tenant_id: int | None = None
) -> None:
    await config_service.delete_special_day(session, _tid(tenant_id), actor, special_day_id)


# ---- Báo giá


async def quote(session: AsyncSession, data: QuoteIn, *, tenant_id: int | None = None) -> QuoteOut:
    return await config_service.quote(session, _tid(tenant_id), data)


# ---- Lịch, tìm mã, đặt tại quầy, thông tin booking / vé


async def calendar(
    session: AsyncSession,
    day: dt.date,
    *,
    can_counter_book: bool,
    can_create_session: bool,
    tenant_id: int | None = None,
) -> CalendarOut:
    """Lịch 1 ngày; ``can_*`` = quyền của người xem do lớp gọi xác định."""
    return await booking_service.calendar(
        session, _tid(tenant_id), day, can_counter_book, can_create_session
    )


async def search_code(
    session: AsyncSession, code: str, *, tenant_id: int | None = None
) -> SearchResult:
    return await booking_service.search(session, _tid(tenant_id), code)


async def get_item(session: AsyncSession, code: str, *, tenant_id: int | None = None) -> ItemOut:
    return await booking_service.get_item(session, _tid(tenant_id), code)


async def room_sources(
    session: AsyncSession, codes: list[str], *, tenant_id: int | None = None
) -> list[RoomSource]:
    """Khối booking theo mã con (phòng chơi, T-017) – có ``customer_ref``; chỉ đọc."""
    return await rooms_feed.by_codes(session, _tid(tenant_id), codes)


async def room_sources_ending_after(
    session: AsyncSession,
    after: dt.datetime,
    play_dates: list[dt.date],
    *,
    tenant_id: int | None = None,
) -> list[RoomSource]:
    """Khối booking các ngày ``play_dates`` chưa kết thúc tại ``after`` (backfill phòng chơi)."""
    return await rooms_feed.ending_after(session, _tid(tenant_id), after, play_dates)


# ------------------------------------------------------------------ khu hội viên (T-018)


async def paid_items(
    session: AsyncSession,
    refs: list[str],
    from_at: dt.datetime,
    to_at: dt.datetime,
    *,
    tenant_id: int | None = None,
) -> list[PaidItem]:
    """Booking + vé **đã thanh toán** của các ref, ``paid_at`` trong ``[from_at, to_at)``."""
    return await member_history.paid_items(session, _tid(tenant_id), refs, from_at, to_at)


async def paid_item(
    session: AsyncSession, refs: list[str], code: str, *, tenant_id: int | None = None
) -> PaidItem | None:
    """Một khoản đã thanh toán (mã con booking / mã vé) của các ref, không có -> None."""
    return await member_history.paid_item(session, _tid(tenant_id), refs, code)


async def paid_months(
    session: AsyncSession,
    refs: list[str],
    since: dt.datetime,
    tz: ZoneInfo,
    *,
    tenant_id: int | None = None,
) -> list[dt.date]:
    """Các tháng (ngày 1, theo ``tz``) có khoản đã thanh toán từ ``since``, mới nhất trước."""
    return await member_history.paid_months(session, _tid(tenant_id), refs, since, tz)


async def upcoming_bookings(
    session: AsyncSession, refs: list[str], after: dt.datetime, *, tenant_id: int | None = None
) -> list[UpcomingBooking]:
    """Khối booking của các ref chưa kết thúc tại ``after``, theo giờ bắt đầu."""
    return await member_history.upcoming(session, _tid(tenant_id), refs, after)


async def customer_stats(
    session: AsyncSession, refs: list[str], *, tenant_id: int | None = None
) -> dict[str, CustomerStats]:
    """Số lượt đặt + tổng phút theo ``customer_ref`` (màn Hội viên, chỉ đọc)."""
    return await customer_history.stats(session, _tid(tenant_id), refs)


async def customer_bookings(
    session: AsyncSession,
    refs: list[str],
    limit: int = 5,
    offset: int = 0,
    *,
    tenant_id: int | None = None,
) -> list[CustomerBookingRow]:
    """Booking mới nhất trước của các ``customer_ref`` (phân trang bằng ``offset``)."""
    return await customer_history.recent(session, _tid(tenant_id), refs, limit, offset)


async def create_counter_order(
    session: AsyncSession,
    actor: Actor,
    data: CounterOrderIn,
    customer: CustomerSnapshot,
    note: str | None = None,
    *,
    tenant_id: int | None = None,
) -> CounterOrderOut:
    """Đặt tại quầy: 1 lần bấm = 1 đơn, 1–20 khối cùng ngày, all-or-nothing (T-019)."""
    return await booking_service.create_counter_order(
        session, _tid(tenant_id), actor, data, customer, note
    )


async def collect_order(
    session: AsyncSession,
    actor: Actor,
    order_code: str,
    data: OrderCollectIn,
    *,
    tenant_id: int | None = None,
) -> OrderCollectOut:
    """Thu cả đơn: mọi khối chưa thanh toán -> tiền mặt. 404 E-BOOK-3 · 409 E-BOOK-4."""
    return await orders.collect_order(session, _tid(tenant_id), actor, order_code, data)


# ---- Sự kiện / vé


async def create_session(
    session: AsyncSession,
    actor: Actor,
    data: SessionCreate,
    *,
    can_register: bool = True,
    can_delete: bool = True,
    tenant_id: int | None = None,
) -> SessionOut:
    return await session_service.create_session(
        session, _tid(tenant_id), actor, data, can_register, can_delete
    )


async def get_session(
    session: AsyncSession,
    code: str,
    *,
    can_register: bool,
    can_delete: bool,
    tenant_id: int | None = None,
) -> SessionOut:
    """``can_*`` = quyền của người xem; engine thêm điều kiện nghiệp vụ (BR-024, BR-025)."""
    return await session_service.get_session(
        session, _tid(tenant_id), code, can_register, can_delete
    )


async def delete_session(
    session: AsyncSession, actor: Actor, code: str, version: int, *, tenant_id: int | None = None
) -> SessionOut:
    return await session_service.delete_session(session, _tid(tenant_id), actor, code, version)


async def register_ticket(
    session: AsyncSession,
    actor: Actor,
    session_code: str,
    customer: CustomerSnapshot,
    note: str | None = None,
    *,
    tenant_id: int | None = None,
) -> ItemOut:
    return await session_service.register_ticket(
        session, _tid(tenant_id), actor, session_code, customer, note
    )


# ---- Thu tiền, Không thu được, Lịch sử giao dịch


async def collect(
    session: AsyncSession, actor: Actor, code: str, data: CollectIn, *, tenant_id: int | None = None
) -> ItemOut:
    return await payment_service.collect(session, _tid(tenant_id), actor, code, data)


async def mark_uncollectible(
    session: AsyncSession,
    actor: Actor,
    code: str,
    data: UncollectibleIn,
    *,
    tenant_id: int | None = None,
) -> ItemOut:
    return await payment_service.mark_uncollectible(session, _tid(tenant_id), actor, code, data)


async def list_transactions(
    session: AsyncSession, query: TransactionsQuery, *, tenant_id: int | None = None
) -> TransactionsOut:
    return await transactions.list_transactions(session, _tid(tenant_id), query)


# ---- Báo cáo & phân tích (chỉ đọc)


async def report(
    session: AsyncSession,
    period: tuple[dt.date, dt.date],
    previous: tuple[dt.date, dt.date],
    previous_until: dt.datetime | None = None,
    *,
    tenant_id: int | None = None,
) -> ReportFigures:
    """Doanh thu, lượt đặt, theo ngày / sân, công suất của kỳ; kỳ trước chỉ tính tổng.

    ``previous_until``: so cùng mốc – kỳ trước chỉ tính booking / sự kiện bắt đầu trước mốc này.
    Không commit; người gọi đặt REPEATABLE READ để các số khớp nhau (NFR-002).
    """
    return await report_figures.figures(session, _tid(tenant_id), period, previous, previous_until)


# ---- Đặt online (T-008, ADR-007)


async def public_calendar(
    session: AsyncSession, day: dt.date, *, tenant_id: int | None = None
) -> PublicCalendar:
    """Lịch cho khách: trạng thái + giá từng ô, không thông tin của người khác."""
    return await online_service.public_calendar(session, _tid(tenant_id), day)


async def create_checkout(
    session: AsyncSession,
    data: CheckoutCreate,
    customer: CustomerSnapshot,
    hold_minutes: int,
    *,
    tenant_id: int | None = None,
) -> CheckoutCreated:
    """Giữ chỗ + cấp mã; trả ``token`` truy cập **một lần** (DB chỉ lưu hash)."""
    return await online_service.create_checkout(
        session, _tid(tenant_id), data, customer, hold_minutes
    )


async def get_checkout(
    session: AsyncSession, token: str, *, tenant_id: int | None = None
) -> CheckoutView:
    return await online_service.get_checkout(session, _tid(tenant_id), token)


async def count_pending_checkouts(session: AsyncSession, *, tenant_id: int | None = None) -> int:
    """Số lượt đặt online đang chờ thanh toán."""
    return await online_service.count_pending_checkouts(session, _tid(tenant_id))


async def lookup(
    session: AsyncSession, code: str, phone: str, *, tenant_id: int | None = None
) -> LookupResult:
    """Tra cứu theo mã + SĐT đã chuẩn hóa; không khớp -> 404 ``E-WEB-7``."""
    return await online_service.lookup(session, _tid(tenant_id), code, phone)


async def apply_online_payment(
    session: AsyncSession, data: OnlinePaymentIn, *, tenant_id: int | None = None
) -> OnlinePaymentResult:
    """Áp giao dịch đã xác thực (module thanh toán gọi, cùng transaction ghi giao dịch)."""
    return await online_service.apply_online_payment(session, _tid(tenant_id), data)


# ---- Vé sự kiện online + lịch hội viên (T-023)


async def event_info(
    session: AsyncSession,
    code: str,
    refs: list[str] | None = None,
    *,
    tenant_id: int | None = None,
) -> EventInfo:
    """Sự kiện cho khách (không danh sách người mua); ``refs`` của hội viên -> ``my_tickets``.
    Không có -> 404 ``E-NOT-FOUND``."""
    return await ticket_online.event_info(session, _tid(tenant_id), code, refs)


async def create_ticket_checkout(
    session: AsyncSession,
    event_code: str,
    seats: int,
    customer: CustomerSnapshot,
    hold_minutes: int,
    *,
    tenant_id: int | None = None,
) -> CheckoutCreated:
    """Giữ ``seats`` ghế + cấp mã đơn; ``token`` trả **một lần**. Lỗi: E-WEB-1 (số vé),
    E-WEB-4 (SĐT đang có lượt chờ), E-WEB-9 (đã bắt đầu / đã hủy), E-WEB-10 (hết chỗ, kèm
    ``remaining``), E-WEB-11 (giá 0 – đăng ký tại quầy), E-NOT-FOUND."""
    return await ticket_online.create_ticket_checkout(
        session, _tid(tenant_id), event_code, seats, customer, hold_minutes
    )


async def member_calendar(
    session: AsyncSession, day: dt.date, refs: list[str], *, tenant_id: int | None = None
) -> MemberCalendar:
    """Lịch công khai + đánh dấu ô của mình (``mine`` + mã đơn) và sự kiện đã có vé."""
    return await member_cal.member_calendar(session, _tid(tenant_id), day, refs)


async def member_order(
    session: AsyncSession, refs: list[str], order_code: str, *, tenant_id: int | None = None
) -> MemberOrder:
    """Đơn đặt sân của chính khách (theo ``refs``); khác -> 404 ``E-NOT-FOUND``."""
    return await member_cal.member_order(session, _tid(tenant_id), refs, order_code)


# ---- Vận hành


async def ensure_tenant(
    session: AsyncSession,
    code: str,
    name: str,
    timezone: str = "Asia/Ho_Chi_Minh",
    *,
    tenant_id: int | None = None,
) -> None:
    """Tạo tenant nếu chưa có (seed / bản chạy mới); đã có thì cập nhật tên."""
    tid = _tid(tenant_id)
    tenant = await session.get(Tenant, tid)
    if tenant is None:
        session.add(
            Tenant(
                id=tid,
                code=code,
                name=name,
                timezone=timezone,
                settings=dict(DEFAULT_TENANT_SETTINGS),
                version=1,
            )
        )
    else:
        tenant.code, tenant.name = code, name
    await session.flush()


async def publish_outbox(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Worker gọi định kỳ: phát sự kiện outbox qua ``core.events``."""
    return await outbox.publish_pending(session_factory)


async def expire_holds(session: AsyncSession) -> int:
    """Worker gọi mỗi 30 giây (không commit): giữ chỗ quá hạn -> ``expired``, trả khung."""
    return await holds.expire_holds(session)


async def rename_customer(
    session: AsyncSession, refs: list[str], name: str, *, tenant_id: int | None = None
) -> int:
    """Tên khách trên booking / vé của hồ sơ (các ``customer_ref``) đổi theo Họ tên mới.

    Không commit; trả số booking + vé đã đổi (ghi vào nhật ký ``member.self_update``)."""
    return await customer_history.rename_customer(session, _tid(tenant_id), refs, name)
