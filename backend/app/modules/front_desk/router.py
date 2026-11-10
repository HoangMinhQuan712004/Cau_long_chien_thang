"""Nghiệp vụ quầy (đặc thù dự án): ghép Hội viên + Booking engine (T-006 §1).

Snapshot khách luôn dựng ở **server** từ hồ sơ Hội viên (ADR-004 S8) – client chỉ gửi mã hội viên
hoặc thông tin hồ sơ tạm. Hồ sơ tạm + booking/vé nằm trong **một transaction** (``idem.run``):
cùng commit hoặc cùng rollback.
"""

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor
from app.core.db import SessionDep
from app.core.errors import AppError
from app.core.idempotency import IdempotencyDep
from app.core.permissions import Perm, Principal, require
from app.core.privacy import mask_phone
from app.core.schemas import StrictIn
from app.modules.booking_engine import api as engine
from app.modules.booking_engine.dto import (
    Actor,
    CancelIn,
    CancelPreview,
    CollectQrInfo,
    CounterBlockIn,
    CounterOrderIn,
    CounterOrderOut,
    CustomerSnapshot,
    ItemOut,
    OrderCancelIn,
    OrderCancelOut,
    RecurringCounts,
    RecurringCreated,
    RecurringIn,
    RecurringPreview,
)
from app.modules.members import api as members
from app.modules.members.api import CustomerIn
from app.modules.payments import api as payments
from app.modules.payments.api import BankInfo
from app.modules.play_rooms import api as rooms

router = APIRouter(prefix="/front-desk", tags=["front-desk"])

CounterBooker = Annotated[Principal, Depends(require(Perm.BOOKING_COUNTER_CREATE))]
RecurringBooker = Annotated[Principal, Depends(require(Perm.BOOKING_RECURRING))]
OrdersViewer = Annotated[Principal, Depends(require(Perm.BOOKING_ORDERS_VIEW))]
Canceller = Annotated[Principal, Depends(require(Perm.BOOKING_CANCEL))]
Collector = Annotated[Principal, Depends(require(Perm.BOOKING_COLLECT))]
TicketSeller = Annotated[Principal, Depends(require(Perm.BOOKING_TICKET_CREATE))]


class FrontDeskBookingIn(StrictIn):
    """Một lần bấm Đặt sân = một đơn (T-019 phương án A).

    ``blocks``: 1–20 khối cùng ``date``. Vẫn nhận dạng cũ một khối
    (``resource_code``, ``start_hour``, ``end_hour``) – không gửi cả hai dạng.
    """

    date: dt.date
    blocks: list[CounterBlockIn] | None = Field(default=None, min_length=1, max_length=20)
    resource_code: str | None = Field(default=None, max_length=10)
    start_hour: int | None = Field(default=None, ge=0, le=23)
    end_hour: int | None = Field(default=None, ge=1, le=24)
    customer: CustomerIn

    @model_validator(mode="after")
    def _one_shape(self) -> "FrontDeskBookingIn":
        single = (self.resource_code, self.start_hour, self.end_hour)
        if self.blocks is None and any(v is None for v in single):
            raise ValueError("Cần blocks, hoặc đủ resource_code / start_hour / end_hour.")
        if self.blocks is not None and any(v is not None for v in single):
            raise ValueError("Gửi blocks hoặc một khối, không gửi cả hai.")
        return self

    def to_order(self) -> CounterOrderIn:
        blocks = self.blocks or [
            CounterBlockIn(
                resource_code=self.resource_code,
                start_hour=self.start_hour,
                end_hour=self.end_hour,
            )
        ]
        return CounterOrderIn(date=self.date, blocks=blocks)


class TicketIn(StrictIn):
    customer: CustomerIn


def actor_of(p: Principal) -> Actor:
    return Actor(type=p.actor_type, id=p.actor_id, label=p.label)


async def customer_snapshot(
    session: AsyncSession, data: CustomerIn, principal: Principal
) -> tuple[CustomerSnapshot, str | None]:
    """Tra / tạo hồ sơ khách rồi dựng snapshot cho engine; trả kèm ghi chú (hồ sơ tạm, OQ-18)."""
    profile = await members.resolve_customer(
        session,
        data,
        AuditActor(type=principal.actor_type, id=principal.actor_id, label=principal.label),
    )
    snapshot = CustomerSnapshot(
        ref_id=profile.ref,
        kind=profile.kind,
        display_name=profile.full_name,
        phone=profile.phone,
        member_code=profile.member_code,
        tier=profile.tier,
    )
    return snapshot, data.temp.note if data.temp else None


def _for_viewer(item: ItemOut, principal: Principal) -> ItemOut:
    """Engine liệt kê mọi thao tác hợp lệ; Nhân viên không thấy ``cancel`` (T-051 AC1)."""
    if not principal.has(Perm.BOOKING_CANCEL):
        item.actions = [a for a in item.actions if a != "cancel"]
        item.cancel_phase = None
    return item


@router.post("/bookings", response_model=CounterOrderOut, status_code=status.HTTP_201_CREATED)
async def create_booking(
    data: FrontDeskBookingIn,
    principal: CounterBooker,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Đặt sân tại quầy: 1 lần bấm = **1 đơn** (mã chung), 1–20 khối hôm nay -> mỗi khối một
    booking Chưa thanh toán mã ``{mã đơn}-NN``. Cùng sân, giờ liền nhau -> gộp một khối.

    All-or-nothing. Lỗi: E-001/E-002 (hồ sơ tạm, khối trùng giờ nhau), E-014 (không có hội
    viên), E-018 (SĐT là của hội viên), E-004 (khung đã qua), E-CFG-10 (khung không bán),
    E-019 (thiếu giá), 409 E-003 kèm ``conflicts`` (vừa có người đặt), 403 E-AUTH-2 (ngày khác
    hôm nay – cả Admin; ngày sau chỉ Đặt sự kiện).
    """

    async def run() -> CounterOrderOut:
        snapshot, note = await customer_snapshot(session, data.customer, principal)
        out = await engine.create_counter_order(
            session, actor_of(principal), data.to_order(), snapshot, note
        )
        out.bookings = [_for_viewer(b, principal) for b in out.bookings]
        return out

    return await idem.run(session, principal.key, run, status_code=status.HTTP_201_CREATED)


@router.post(
    "/sessions/{code}/tickets", response_model=ItemOut, status_code=status.HTTP_201_CREATED
)
async def register_ticket(
    code: str,
    data: TicketIn,
    principal: TicketSeller,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Đăng ký vé tại quầy: sự kiện hôm nay chưa kết thúc, còn chỗ -> vé Chưa thanh toán.

    Lỗi: E-001/E-002/E-014/E-018 (khách), E-004 (không phải hôm nay / đã kết thúc), E-024 (đủ chỗ).
    """

    async def run() -> ItemOut:
        snapshot, note = await customer_snapshot(session, data.customer, principal)
        item = await engine.register_ticket(session, actor_of(principal), code, snapshot, note)
        return _for_viewer(item, principal)

    return await idem.run(session, principal.key, run, status_code=status.HTTP_201_CREATED)


# ------------------------------------------------------------------ đặt sân định kỳ (T-035)


class RecurringPreviewIn(RecurringIn):
    """Như lúc tạo; ``customer`` không bắt buộc (xem trước không dựng hồ sơ khách)."""

    customer: CustomerIn | None = None


class RecurringBookingIn(RecurringIn):
    customer: CustomerIn


def _recurring(data: RecurringIn) -> RecurringIn:
    return RecurringIn(**data.model_dump(include=set(RecurringIn.model_fields)))


@router.post("/recurring/preview", response_model=RecurringPreview)
async def preview_recurring(
    data: RecurringPreviewIn, _: RecurringBooker, session: SessionDep
) -> RecurringPreview:
    """Xem trước đặt sân định kỳ (chỉ Admin, không ghi): từng buổi (ngày, thứ, giờ, giá gốc, giá
    sau giảm, ``ok`` / ``reason``) + tổng. ``reason``: booked · event · hold · closed · inactive ·
    past · no_price. Lỗi 422: không chọn thứ, giờ sai, từ ngày < hôm nay, > 92 ngày, > 60 buổi,
    % ngoài 0–100. 403 không phải Admin."""
    return await engine.preview_recurring(session, _recurring(data))


@router.post("/recurring", response_model=RecurringCreated, status_code=status.HTTP_201_CREATED)
async def create_recurring(
    data: RecurringBookingIn,
    principal: RecurringBooker,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Đặt sân định kỳ (chỉ Admin): **một đơn** (mã theo ngày buổi đầu) + mỗi buổi một booking
    Chưa thanh toán, giảm % phân bổ vào từng buổi. Thu tiền bằng "Thu cả đơn" (T-019).

    Tất cả hoặc không: có buổi không đặt được (kể cả vừa bị người khác đặt) -> 409 ``E-BOOK-5``
    "Có n buổi không đặt được." kèm ``conflicts: [{date, start, reason, reason_text}]``.
    Lỗi khác như xem trước; khách: E-014 / E-018 / E-001 như đặt quầy.
    """

    async def run() -> RecurringCreated:
        snapshot, _note = await customer_snapshot(session, data.customer, principal)
        return await engine.create_recurring(
            session, actor_of(principal), _recurring(data), snapshot
        )

    return await idem.run(session, principal.key, run, status_code=status.HTTP_201_CREATED)


class _OrderBase(BaseModel):
    order_code: str
    customer_name: str
    resource_code: str
    resource_name: str
    weekdays: list[int] = Field(description="ISO 1 = T2 … 7 = CN (các thứ có buổi)")
    start_hour: int
    end_hour: int
    date_from: dt.date = Field(description="Ngày buổi đầu")
    date_to: dt.date = Field(description="Ngày buổi cuối")
    sessions: int
    original_amount: int
    discount_pct: int
    discount_amount: int
    total: int = Field(description="Phải thu (sau giảm)")
    status: Literal["unpaid", "paid", "uncollectible", "cancelled"]
    created_at: dt.datetime
    created_by: str


class RecurringOrderOut(_OrderBase):
    """Một đơn định kỳ (T-039) – SĐT đã che."""

    phone_masked: str | None


class RecurringOrderListOut(BaseModel):
    items: list[RecurringOrderOut]
    counts: RecurringCounts = Field(description="Theo q, bỏ qua status")
    page: int
    size: int
    total: int


@router.get("/recurring", response_model=RecurringOrderListOut)
async def list_recurring(
    _: RecurringBooker,
    session: SessionDep,
    status_: Annotated[
        Literal["unpaid", "paid", "uncollectible", "cancelled"] | None, Query(alias="status")
    ] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    size: Annotated[int, Query(ge=1, le=50)] = 20,
):
    """Màn "Đơn định kỳ" (chỉ Admin, T-039): mới nhất trước, lọc trạng thái, tìm theo mã đơn / tên
    khách / SĐT. Thu cả đơn vẫn qua ``POST /booking/orders/{code}/collect`` (T-019)."""
    out = await engine.list_recurring(session, status_, q, page, size)
    return RecurringOrderListOut(
        items=[
            RecurringOrderOut(
                **row.model_dump(exclude={"customer_phone"}),
                phone_masked=mask_phone(row.customer_phone),
            )
            for row in out.items
        ],
        counts=out.counts,
        page=out.page,
        size=out.size,
        total=out.total,
    )


# ------------------------------------------------------------------ đơn đặt sân (T-041)


class OrderOut(_OrderBase):
    """Một đơn đặt sân (quầy / online / định kỳ), không gồm vé. SĐT đầy đủ như các màn quản trị
    khác (người dùng chốt 2026-11-09); quyền ``booking.orders.view``."""

    phone: str
    kind: Literal["single", "recurring"] = Field(description="single = đơn ngày · recurring")
    source: Literal["counter", "online"]
    member_code: str | None = Field(description="Mã HV khi khách là hội viên")
    resource_codes: list[str]
    resource_names: list[str] = Field(description="Đơn ngày có thể nhiều sân")
    play_date: dt.date = Field(description="Ngày chơi (định kỳ: ngày buổi đầu)")
    blocks: int = Field(description="Số khối (đơn ngày) / số buổi (định kỳ)")


class OrderCountsOut(BaseModel):
    all: RecurringCounts
    single: RecurringCounts
    recurring: RecurringCounts


class OrderListOut(BaseModel):
    items: list[OrderOut]
    counts: OrderCountsOut = Field(description="Loại × trạng thái theo q + ngày")
    page: int
    size: int
    total: int


@router.get("/orders", response_model=OrderListOut)
async def list_orders(
    _: OrdersViewer,
    session: SessionDep,
    kind: Annotated[Literal["all", "single", "recurring"], Query()] = "all",
    status_: Annotated[
        Literal["unpaid", "paid", "uncollectible", "cancelled"] | None, Query(alias="status")
    ] = None,
    q: Annotated[str | None, Query(max_length=100)] = None,
    date_from: Annotated[dt.date | None, Query(description="Ngày chơi từ (khối bất kỳ)")] = None,
    date_to: Annotated[dt.date | None, Query(description="Ngày chơi đến")] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    size: Annotated[int, Query(ge=1, le=50)] = 20,
):
    """Màn "Đơn đặt sân" (chỉ Admin, T-041): mọi đơn quầy / online / định kỳ (không gồm vé, không
    gồm lượt giữ chỗ chưa trả tiền), mới nhất trước. Lọc loại × trạng thái + khoảng ngày chơi (đơn
    có khối trong khoảng); tìm mã đơn / mã con / tên / SĐT. Thu cả đơn: ``POST
    /booking/orders/{code}/collect`` (T-019). Ngày sai thứ tự -> 422 E-016."""
    if date_from and date_to and date_from > date_to:
        raise AppError("E-016", "Từ ngày không được sau Đến ngày.", 422)
    out = await engine.list_orders(
        session,
        kind=None if kind == "all" else kind,
        status=status_,
        q=q,
        date_from=date_from,
        date_to=date_to,
        page=page,
        size=size,
    )
    return OrderListOut(
        items=[
            OrderOut(**row.model_dump(exclude={"customer_phone"}), phone=row.customer_phone)
            for row in out.items
        ],
        counts=OrderCountsOut(**out.counts.model_dump()),
        page=out.page,
        size=out.size,
        total=out.total,
    )


# ---------------------------------------------------------------- hủy booking / vé (T-051)
# Ở quầy: hủy cả đơn tra trận qua play_rooms rồi gọi engine (engine không biết phòng, ADR-003)


@router.post("/items/{code}/cancel", response_model=ItemOut)
async def cancel_item(
    code: Annotated[str, Path(max_length=40)],
    data: CancelIn,
    principal: Canceller,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Hủy một booking hoặc vé (chỉ Admin, T-052): đã thu hủy được mọi lúc, kể cả đang chơi và đã
    qua; chưa thu chỉ trước giờ bắt đầu. Nhả khung / chỗ ngay, không tự hoàn tiền.

    422 E-001 (lý do) · E-PAY-5 (đã bắt đầu mà chưa thu) · E-PAY-7 (đã thu mà chưa xác nhận hoàn) ·
    409 E-PAY-6 (đã hủy / Không thu được) · E-012 (``version`` cũ) · 404.
    """

    async def run() -> ItemOut:
        return await engine.cancel_item(session, actor_of(principal), code, data)

    return await idem.run(session, principal.key, run)


class CollectQrOut(CollectQrInfo):
    bank: BankInfo = Field(description="Như trang thanh toán online: ngân hàng, số TK, chủ TK, QR")


def _no_bank() -> AppError:
    return AppError(
        "E-PAY-9",
        "Chưa cài đặt nhận tiền chuyển khoản. Vào Cài đặt thanh toán hoặc thu tiền mặt.",
        409,
    )


@router.get("/orders/{order_code}/collect-qr", response_model=CollectQrOut)
async def order_collect_qr(
    order_code: Annotated[str, Path(max_length=40)],
    _: Collector,
    session: SessionDep,
    response: Response,
):
    """Thu cả đơn bằng QR chuyển khoản (T-058) – popup gọi lại tới khi ``status`` khác ``unpaid``.

    Số tiền = tổng khối Chưa thanh toán (như ``POST /booking/orders/{code}/collect``); nội dung
    chuyển khoản ``pay_ref`` = mã đơn bỏ gạch. Tiền về đúng số -> webhook thu cả đơn; lệch số ->
    Tiền về cần xử lý (cần hoàn). ``status``: ``unpaid`` / ``paid`` (tiền đã về hết) / ``closed``
    (hết khối chưa thu do Không thu được / hủy – xử lý ở máy khác). 404 E-BOOK-3 · 409 E-PAY-9
    (chưa cài nhận chuyển khoản).
    """
    response.headers["Cache-Control"] = "no-store"
    info = await engine.collect_qr_info(session, order_code)
    bank = await payments.bank_info(session, info.amount, info.pay_ref)
    if bank is None:
        raise _no_bank()
    return CollectQrOut(**info.model_dump(), bank=bank)


@router.get("/items/{code}/collect-qr", response_model=CollectQrOut)
async def item_collect_qr(
    code: Annotated[str, Path(max_length=40)],
    _: Collector,
    session: SessionDep,
    response: Response,
):
    """Thu một buổi bằng QR (T-065): ``order_code`` = mã của khối, ``pay_ref`` = mã con bỏ gạch
    (bắt đầu bằng mã đơn chung), số tiền = tiền của khối, ``blocks = 1``. Đã thu -> ``status =
    paid``, ``amount = 0``. Tiền về đúng số -> chỉ khối đó Đã thanh toán; lệch -> cần hoàn.
    404 E-BOOK-3 · 422 E-PAY-1 (vé / online) · 409 E-PAY-9. ``status``: unpaid / paid / closed.
    """
    response.headers["Cache-Control"] = "no-store"
    info = await engine.item_collect_qr_info(session, code)
    bank = await payments.bank_info(session, info.amount, info.pay_ref)
    if bank is None:
        raise _no_bank()
    return CollectQrOut(**info.model_dump(), bank=bank)


@router.get("/orders/{order_code}/cancel-preview", response_model=CancelPreview)
async def order_cancel_preview(
    order_code: Annotated[str, Path(max_length=40)], _: Canceller, session: SessionDep
):
    """Xem trước hủy cả đơn: khối sẽ hủy, khối bỏ qua kèm lý do, tổng tiền. 404 E-BOOK-3."""
    codes = await engine.order_block_codes(session, order_code)
    played = await rooms.played_booking_codes(session, codes)
    return await engine.order_cancel_preview(session, order_code, played)


@router.post("/orders/{order_code}/cancel", response_model=OrderCancelOut)
async def cancel_order(
    order_code: Annotated[str, Path(max_length=40)],
    data: OrderCancelIn,
    principal: Canceller,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Hủy các khối ``codes`` của đơn (lấy từ xem trước). Kiểm tra lại từng khối lúc hủy: khối đã
    bắt đầu / có trận sau lúc xem trước vào ``skipped``, buổi đã chơi giữ nguyên.

    422 E-001 (lý do; ``codes`` rỗng hoặc có mã ngoài đơn) · E-PAY-7 cho cả lệnh · 404 E-BOOK-3.
    """

    async def run() -> OrderCancelOut:
        codes = await engine.order_block_codes(session, order_code)
        played = await rooms.played_booking_codes(session, codes)
        return await engine.cancel_order(session, actor_of(principal), order_code, data, played)

    return await idem.run(session, principal.key, run)
