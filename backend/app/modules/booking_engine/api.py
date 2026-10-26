"""MẶT TIỀN DUY NHẤT của booking engine (ADR-003).

Module khác (và router HTTP của engine) chỉ gọi các hàm ở đây, vào/ra bằng DTO (``dto.py``).

Quy ước transaction: hàm ghi **không commit** – người gọi sở hữu transaction (router commit qua
``Idempotency.run``; BFF có thể gộp thao tác của nhiều module trong cùng một transaction).
``tenant_id`` mặc định là tenant của bản chạy (``TENANT_ID``).
"""

import datetime as dt

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.booking_engine import (
    booking_service,
    config_service,
    holds,
    outbox,
    payment_service,
    session_service,
    transactions,
)
from app.modules.booking_engine.dto import (
    Actor,
    CalendarOut,
    CollectIn,
    CounterBookingIn,
    CustomerSnapshot,
    ItemOut,
    PriceTable,
    PriceTableUpdate,
    PublicPrices,
    QuoteIn,
    QuoteOut,
    ResourceCreate,
    ResourceList,
    ResourceOut,
    ResourceUpdate,
    SearchResult,
    SessionCreate,
    SessionOut,
    SpecialDayIn,
    SpecialDayOut,
    TransactionsOut,
    TransactionsQuery,
    UncollectibleIn,
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


async def create_counter_booking(
    session: AsyncSession,
    actor: Actor,
    data: CounterBookingIn,
    customer: CustomerSnapshot,
    note: str | None = None,
    *,
    tenant_id: int | None = None,
) -> ItemOut:
    return await booking_service.create_counter_booking(
        session, _tid(tenant_id), actor, data, customer, note
    )


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
