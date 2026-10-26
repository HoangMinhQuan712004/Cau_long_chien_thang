"""HTTP ``/api/v1/booking/**`` của engine.

Chỉ gọi ``api.py``; khai báo quyền theo bảng quyền tập trung (``core.permissions``).

Mọi lệnh ghi bắt buộc header ``Idempotency-Key`` (UUID v4) và chạy trong ``Idempotency.run``
(một transaction: nghiệp vụ + nhật ký + outbox + kết quả idempotency).
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.db import SessionDep
from app.core.idempotency import IdempotencyDep
from app.core.permissions import Perm, Principal, require
from app.core.ratelimit import rate_limit
from app.modules.booking_engine import api
from app.modules.booking_engine.dto import (
    Actor,
    CalendarOut,
    ItemOut,
    PriceTable,
    PriceTableUpdate,
    QuoteIn,
    QuoteOut,
    ResourceCreate,
    ResourceList,
    ResourceOut,
    ResourceUpdate,
    SearchResult,
    SessionCreate,
    SessionDelete,
    SessionOut,
    SpecialDayIn,
    SpecialDayOut,
)

router = APIRouter(prefix="/booking", tags=["booking"])

ResourceViewer = Annotated[Principal, Depends(require(Perm.BOOKING_RESOURCES_VIEW))]
ConfigManager = Annotated[Principal, Depends(require(Perm.BOOKING_CONFIG_MANAGE))]
Quoter = Annotated[Principal, Depends(require(Perm.BOOKING_QUOTE))]
CalendarViewer = Annotated[Principal, Depends(require(Perm.BOOKING_CALENDAR_VIEW))]
CodeSearcher = Annotated[Principal, Depends(require(Perm.BOOKING_SEARCH))]
ItemViewer = Annotated[Principal, Depends(require(Perm.BOOKING_ITEM_VIEW))]
SessionViewer = Annotated[Principal, Depends(require(Perm.BOOKING_SESSION_VIEW))]
SessionManager = Annotated[Principal, Depends(require(Perm.BOOKING_SESSION_MANAGE))]

ACTION_PERMS = {"collect": Perm.BOOKING_COLLECT, "uncollectible": Perm.BOOKING_UNCOLLECTIBLE}


def _actor(p: Principal) -> Actor:
    return Actor(type=p.actor_type, id=p.actor_id, label=p.label)


def for_viewer(item: ItemOut, p: Principal) -> ItemOut:
    """Chỉ giữ thao tác mà người xem có quyền làm."""
    item.actions = [a for a in item.actions if p.has(ACTION_PERMS[a])]
    return item


# ---------------------------------------------------------------- tài nguyên


@router.get("/resources", response_model=ResourceList)
async def list_resources(_: ResourceViewer, session: SessionDep):
    """Danh sách sân + lịch đang áp dụng + lịch chờ áp dụng (``pending_schedule``)."""
    return await api.list_resources(session)


@router.post("/resources", response_model=ResourceOut, status_code=status.HTTP_201_CREATED)
async def create_resource(
    data: ResourceCreate, principal: ConfigManager, idem: IdempotencyDep, session: SessionDep
):
    """Thêm sân – mã ``S01…`` do hệ thống cấp; giờ hoạt động áp dụng ngay hôm nay."""
    return await idem.run(
        session,
        principal.key,
        lambda: api.create_resource(session, _actor(principal), data),
        status_code=status.HTTP_201_CREATED,
    )


@router.patch("/resources/{code}", response_model=ResourceOut)
async def update_resource(
    code: str,
    data: ResourceUpdate,
    principal: ConfigManager,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Sửa tên / loại / trạng thái / giờ.

    Giờ & cao điểm áp dụng từ ngày mai (D4); ``version`` bắt buộc.
    """
    return await idem.run(
        session,
        principal.key,
        lambda: api.update_resource(session, _actor(principal), code, data),
    )


# ---------------------------------------------------------------- bảng giá


@router.get("/prices", response_model=PriceTable)
async def get_prices(_: ConfigManager, session: SessionDep):
    return await api.get_price_table(session)


@router.put("/prices", response_model=PriceTable)
async def put_prices(
    data: PriceTableUpdate, principal: ConfigManager, idem: IdempotencyDep, session: SessionDep
):
    """Lưu cả bảng giá một lần (đủ mọi ô); ``version`` khác bản hiện tại -> 409 ``E-CFG-7``."""
    return await idem.run(
        session, principal.key, lambda: api.update_price_table(session, _actor(principal), data)
    )


# ---------------------------------------------------------------- ngày Lễ / Tết


@router.get("/special-days", response_model=list[SpecialDayOut])
async def list_special_days(
    _: ConfigManager,
    session: SessionDep,
    year: Annotated[int | None, Query(ge=2000, le=2100)] = None,
):
    return await api.list_special_days(session, year)


@router.post("/special-days", response_model=SpecialDayOut, status_code=status.HTTP_201_CREATED)
async def create_special_day(
    data: SpecialDayIn, principal: ConfigManager, idem: IdempotencyDep, session: SessionDep
):
    return await idem.run(
        session,
        principal.key,
        lambda: api.create_special_day(session, _actor(principal), data),
        status_code=status.HTTP_201_CREATED,
    )


@router.delete(
    "/special-days/{special_day_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_special_day(
    special_day_id: int, principal: ConfigManager, idem: IdempotencyDep, session: SessionDep
):
    return await idem.run(
        session,
        principal.key,
        lambda: api.delete_special_day(session, _actor(principal), special_day_id),
        status_code=status.HTTP_204_NO_CONTENT,
    )


# ---------------------------------------------------------------- báo giá


@router.post(
    "/quote",
    response_model=QuoteOut,
    dependencies=[Depends(rate_limit("booking.quote", 60, key="user"))],
)
async def quote(data: QuoteIn, _: Quoter, session: SessionDep):
    """Giá từng khung 1 giờ + tổng (không ghi dữ liệu) – dùng cho popup Đặt sân."""
    return await api.quote(session, data)


# ---------------------------------------------------------------- lịch, tìm mã, booking / vé


@router.get("/calendar", response_model=CalendarOut)
async def calendar(
    principal: CalendarViewer,
    session: SessionDep,
    day: Annotated[date, Query(alias="date")],
):
    """Lịch 1 ngày: hàng = sân, cột = khung 1 giờ, khối booking / sự kiện / giữ chỗ (BR-001…004)."""
    return await api.calendar(
        session,
        day,
        can_counter_book=principal.has(Perm.BOOKING_COUNTER_CREATE),
        can_create_session=principal.has(Perm.BOOKING_SESSION_MANAGE),
    )


@router.get(
    "/search",
    response_model=SearchResult,
    dependencies=[Depends(rate_limit("booking.search", 60, key="user"))],
)
async def search(
    _: CodeSearcher,
    session: SessionDep,
    code: Annotated[str, Query(max_length=60)] = "",
):
    """Tìm đúng mã booking / sự kiện / vé (bỏ khoảng trắng, không phân biệt hoa thường)."""
    return await api.search_code(session, code)


@router.get("/items/{code}", response_model=ItemOut)
async def get_item(code: str, principal: ItemViewer, session: SessionDep):
    """Thông tin booking hoặc vé: khách, lịch đặt, thanh toán, ``actions`` được phép lúc này."""
    return for_viewer(await api.get_item(session, code), principal)


# ---------------------------------------------------------------- sự kiện


@router.post("/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
async def create_session(
    data: SessionCreate, principal: SessionManager, idem: IdempotencyDep, session: SessionDep
):
    """Đặt sự kiện (chỉ Admin): sân liền nhau × khung liền nhau, hôm nay → hết tháng sau.

    Lỗi: E-001 (trống tên / số chỗ / giá vé), E-009, E-013, E-004, E-CFG-10, E-BOOK-1/2, E-010.
    """
    return await idem.run(
        session,
        principal.key,
        lambda: api.create_session(
            session,
            _actor(principal),
            data,
            can_register=principal.has(Perm.BOOKING_TICKET_CREATE),
            can_delete=principal.has(Perm.BOOKING_SESSION_MANAGE),
        ),
        status_code=status.HTTP_201_CREATED,
    )


@router.get("/sessions/{code}", response_model=SessionOut)
async def get_session(code: str, principal: SessionViewer, session: SessionDep):
    """Popup Sự kiện: số chỗ, vé (mới nhất trước), chỗ đang giữ, ``can{register, delete}``."""
    return await api.get_session(
        session,
        code,
        can_register=principal.has(Perm.BOOKING_TICKET_CREATE),
        can_delete=principal.has(Perm.BOOKING_SESSION_MANAGE),
    )


@router.delete("/sessions/{code}", response_model=SessionOut)
async def delete_session(
    code: str,
    data: SessionDelete,
    principal: SessionManager,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Xóa buổi (chỉ Admin, chưa có vé và chỗ giữ): khung trống lại, mã không dùng lại (E-023)."""
    return await idem.run(
        session,
        principal.key,
        lambda: api.delete_session(session, _actor(principal), code, data.version),
    )
