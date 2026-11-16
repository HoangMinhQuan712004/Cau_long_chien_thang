"""HTTP ``/api/v1/booking/**`` của engine.

Chỉ gọi ``api.py``; khai báo quyền theo bảng quyền tập trung (``core.permissions``).

Mọi lệnh ghi bắt buộc header ``Idempotency-Key`` (UUID v4) và chạy trong ``Idempotency.run``
(một transaction: nghiệp vụ + nhật ký + outbox + kết quả idempotency).
"""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.core.db import SessionDep
from app.core.idempotency import IdempotencyDep
from app.core.middleware import require_origin
from app.core.params import not_found, path_id
from app.core.permissions import Perm, Principal, require
from app.core.ratelimit import rate_limit
from app.modules.booking_engine import api, resource_router
from app.modules.booking_engine.dto import (
    Actor,
    CalendarOut,
    CollectIn,
    ItemOut,
    MoveIn,
    MoveTarget,
    OrderCollectIn,
    OrderCollectOut,
    OrderUncollectibleIn,
    OrderUncollectibleOut,
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
    SessionDelete,
    SessionOut,
    SpecialDayIn,
    SpecialDayOut,
    TransactionsOut,
    TransactionsQuery,
    UncollectibleIn,
)

router = APIRouter(prefix="/booking", tags=["booking"])
# Id ngoài khoảng cột -> 404 như không tồn tại (T-070)
SpecialDayId = path_id("special_day_id", not_found("Không tìm thấy ngày Lễ/Tết."))

ResourceViewer = Annotated[Principal, Depends(require(Perm.BOOKING_RESOURCES_VIEW))]
ConfigManager = Annotated[Principal, Depends(require(Perm.BOOKING_CONFIG_MANAGE))]
ResourceDeleter = Annotated[Principal, Depends(require(Perm.BOOKING_RESOURCES_DELETE))]
Quoter = Annotated[Principal, Depends(require(Perm.BOOKING_QUOTE))]
CalendarViewer = Annotated[Principal, Depends(require(Perm.BOOKING_CALENDAR_VIEW))]
CodeSearcher = Annotated[Principal, Depends(require(Perm.BOOKING_SEARCH))]
ItemViewer = Annotated[Principal, Depends(require(Perm.BOOKING_ITEM_VIEW))]
SessionViewer = Annotated[Principal, Depends(require(Perm.BOOKING_SESSION_VIEW))]
Collector = Annotated[Principal, Depends(require(Perm.BOOKING_COLLECT))]
Mover = Annotated[Principal, Depends(require(Perm.BOOKING_COUNTER_CREATE))]
UncollectibleMarker = Annotated[Principal, Depends(require(Perm.BOOKING_UNCOLLECTIBLE))]
TransactionsViewer = Annotated[Principal, Depends(require(Perm.BOOKING_TRANSACTIONS_VIEW))]
SessionManager = Annotated[Principal, Depends(require(Perm.BOOKING_SESSION_MANAGE))]

ACTION_PERMS = {
    "collect": Perm.BOOKING_COLLECT,
    "uncollectible": Perm.BOOKING_UNCOLLECTIBLE,
    "cancel": Perm.BOOKING_CANCEL,
    "move": Perm.BOOKING_COUNTER_CREATE,  # người dùng chốt 2026-11-09: đặt quầy là đổi sân được
}


def _actor(p: Principal) -> Actor:
    return Actor(type=p.actor_type, id=p.actor_id, label=p.label)


def for_viewer(item: ItemOut, p: Principal) -> ItemOut:
    """Chỉ giữ thao tác mà người xem có quyền làm."""
    item.actions = [a for a in item.actions if p.has(ACTION_PERMS[a])]
    if "cancel" not in item.actions:
        item.cancel_phase = None
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


@router.delete(
    "/resources/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    dependencies=[Depends(require_origin)],
)
async def delete_resource(
    code: str, principal: ResourceDeleter, idem: IdempotencyDep, session: SessionDep
):
    """Xóa sân: ẩn khỏi mọi màn vận hành, giữ lịch sử; mã không dùng lại.

    409 ``E-CFG-11`` (còn lịch chưa kết thúc, kèm ``count``) · 404 (không có / đã xóa).
    """
    return await idem.run(
        session,
        principal.key,
        lambda: api.delete_resource(session, _actor(principal), code),
        status_code=status.HTTP_204_NO_CONTENT,
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


@router.get("/prices/public", response_model=PublicPrices)
async def public_prices(session: SessionDep, response: Response):
    """Bảng giá công khai cho trang chủ – **không cần đăng nhập**, cache 5 phút.

    Chỉ loại sân có sân đang hoạt động; giờ mở cửa / cao điểm theo lịch hôm nay;
    Lễ/Tết từ hôm nay tới hết năm.
    """
    response.headers["Cache-Control"] = "public, max-age=300"
    return await api.public_prices(session)


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


@router.patch("/special-days/{special_day_id}", response_model=SpecialDayOut)
async def update_special_day(
    special_day_id: SpecialDayId,
    data: SpecialDayIn,
    principal: ConfigManager,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Sửa ngày Lễ/Tết (T-063): kiểm chồng bỏ qua chính nó; giá booking / vé đã có không đổi."""
    return await idem.run(
        session,
        principal.key,
        lambda: api.update_special_day(session, _actor(principal), special_day_id, data),
    )


@router.delete(
    "/special-days/{special_day_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
async def delete_special_day(
    special_day_id: SpecialDayId,
    principal: ConfigManager,
    idem: IdempotencyDep,
    session: SessionDep,
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

    Lỗi: E-001 (trống tên / số chỗ / giá vé), E-009, E-013, E-004, E-CFG-10, E-BOOK-2, E-010.
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


# ---------------------------------------------------------------- thu tiền, Không thu được


@router.post("/items/{code}/collect", response_model=ItemOut)
async def collect(
    code: str, data: CollectIn, principal: Collector, idem: IdempotencyDep, session: SessionDep
):
    """Thu tiền mặt (``method="cash"``; ``transfer`` -> 422 ``E-PAY-0`` cho tới T-007).

    Đã đổi trạng thái / ``version`` cũ -> 409 ``E-012``; đã hủy -> 409 ``E-PAY-6``.
    """

    async def run() -> ItemOut:
        return for_viewer(await api.collect(session, _actor(principal), code, data), principal)

    return await idem.run(session, principal.key, run)


@router.post("/orders/{order_code}/collect", response_model=OrderCollectOut)
async def collect_order(
    order_code: Annotated[str, Path(max_length=40)],
    data: OrderCollectIn,
    principal: Collector,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Thu cả đơn (T-019): mọi khối **Chưa thanh toán** của đơn -> tiền mặt, người thu = người
    thao tác. Khối đã thu / Không thu được giữ nguyên. 404 ``E-BOOK-3`` · 409 ``E-BOOK-4``
    (không còn khối chưa thu) · 422 ``E-PAY-0`` (``transfer``)."""

    async def run() -> OrderCollectOut:
        out = await api.collect_order(session, _actor(principal), order_code, data)
        out.bookings = [for_viewer(b, principal) for b in out.bookings]
        return out

    return await idem.run(session, principal.key, run)


@router.post("/orders/{order_code}/uncollectible", response_model=OrderUncollectibleOut)
async def uncollectible_order(
    order_code: Annotated[str, Path(max_length=40)],
    data: OrderUncollectibleIn,
    principal: UncollectibleMarker,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Không thu được cả đơn (T-064): mọi khối **Chưa thanh toán đã tới giờ** -> Không thu được
    (lý do không bắt buộc, ≤ 200); khối chưa tới giờ giữ nguyên (``remaining_unpaid``). 404
    ``E-BOOK-3`` · 409 ``E-BOOK-4`` · 422 ``E-PAY-1`` (đơn online / chưa buổi nào tới giờ)."""

    async def run() -> OrderUncollectibleOut:
        out = await api.uncollectible_order(session, _actor(principal), order_code, data)
        out.bookings = [for_viewer(b, principal) for b in out.bookings]
        return out

    return await idem.run(session, principal.key, run)


@router.post("/items/{code}/uncollectible", response_model=ItemOut)
async def mark_uncollectible(
    code: str,
    data: UncollectibleIn,
    principal: UncollectibleMarker,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Không thu được: lý do 1–200 (E-001); chỉ tại quầy + đã tới giờ chơi (E-PAY-1); E-012."""

    async def run() -> ItemOut:
        item = await api.mark_uncollectible(session, _actor(principal), code, data)
        return for_viewer(item, principal)

    return await idem.run(session, principal.key, run)


# ---------------------------------------------------------------- đổi sân


@router.get("/items/{code}/move-targets", response_model=list[MoveTarget])
async def move_targets(code: str, _: Mover, session: SessionDep):
    """Sân đổi sang được cho booking (cùng ngày, cùng giờ): đang hoạt động, mở cửa đủ khung, còn
    trống – theo thứ tự danh mục, mọi loại sân. 409 E-BOOK-6 · 404."""
    return await api.move_targets(session, code)


@router.post("/items/{code}/move", response_model=ItemOut, dependencies=[Depends(require_origin)])
async def move_booking(
    code: str, data: MoveIn, principal: Mover, idem: IdempotencyDep, session: SessionDep
):
    """Đổi sân một booking: giữ mã, giá đã chốt, tiền đã thu (kể cả đổi khác loại sân).

    409 ``E-BOOK-6`` (vé / sự kiện / giữ chỗ, đã hủy, Không thu được, đã kết thúc, cùng sân) ·
    409 ``E-BOOK-8`` (sân đích đã có lịch) · 422 ``E-BOOK-7`` (sân đích ngừng / đóng cửa khung
    đó) · 404 (mã / sân không có) · 409 ``E-012`` (``version`` cũ).
    """

    async def run() -> ItemOut:
        return for_viewer(await api.move_booking(session, _actor(principal), code, data), principal)

    return await idem.run(session, principal.key, run)


# ---------------------------------------------------------------- lịch sử giao dịch


@router.get("/transactions", response_model=TransactionsOut)
async def list_transactions(
    _: TransactionsViewer,
    session: SessionDep,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    resource: Annotated[
        str | None, Query(max_length=10, description="Dòng có mục ở sân này")
    ] = None,
    method: Annotated[
        Literal["cash", "transfer"] | None, Query(description="transfer gồm cả online")
    ] = None,
    kind: Annotated[
        Literal["in", "refund"] | None, Query(description="Thu tiền / Hoàn tiền")
    ] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
):
    """Lịch sử giao dịch = sổ tiền vào (T-057): mỗi dòng một lần nhận / hoàn tiền, lọc theo ngày
    tiền về (giờ VN, mặc định 7 ngày), 8 dòng / trang. Chỉ xem.

    Thẻ ``cards`` theo bộ lọc ngày + sân. Lỗi: E-016 (từ > đến), E-020 (> 92 ngày).
    """
    return await api.list_transactions(
        session,
        TransactionsQuery(
            date_from=date_from,
            date_to=date_to,
            resource=resource,
            method=method,
            kind=kind,
            q=q,
            page=page,
        ),
    )


# Ngăn chi tiết sân (/admin/san): router phụ, file này đã dài
router.include_router(resource_router.router)
