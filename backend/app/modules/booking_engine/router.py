"""HTTP ``/api/v1/booking/**`` của engine.

Chỉ gọi ``api.py``; khai báo quyền theo bảng quyền tập trung (``core.permissions``).

Mọi lệnh ghi bắt buộc header ``Idempotency-Key`` (UUID v4) và chạy trong ``Idempotency.run``
(một transaction: nghiệp vụ + nhật ký + outbox + kết quả idempotency).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.db import SessionDep
from app.core.idempotency import IdempotencyDep
from app.core.permissions import Perm, Principal, require
from app.core.ratelimit import rate_limit
from app.modules.booking_engine import api
from app.modules.booking_engine.dto import (
    Actor,
    PriceTable,
    PriceTableUpdate,
    QuoteIn,
    QuoteOut,
    ResourceCreate,
    ResourceList,
    ResourceOut,
    ResourceUpdate,
    SpecialDayIn,
    SpecialDayOut,
)

router = APIRouter(prefix="/booking", tags=["booking"])

ResourceViewer = Annotated[Principal, Depends(require(Perm.BOOKING_RESOURCES_VIEW))]
ConfigManager = Annotated[Principal, Depends(require(Perm.BOOKING_CONFIG_MANAGE))]
Quoter = Annotated[Principal, Depends(require(Perm.BOOKING_QUOTE))]


def _actor(p: Principal) -> Actor:
    return Actor(type=p.actor_type, id=p.actor_id, label=p.label)


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
