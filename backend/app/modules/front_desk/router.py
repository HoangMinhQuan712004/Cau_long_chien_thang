"""Nghiệp vụ quầy (đặc thù dự án): ghép Hội viên + Booking engine (T-006 §1).

Snapshot khách luôn dựng ở **server** từ hồ sơ Hội viên (ADR-004 S8) – client chỉ gửi mã hội viên
hoặc thông tin hồ sơ tạm. Hồ sơ tạm + booking/vé nằm trong **một transaction** (``idem.run``):
cùng commit hoặc cùng rollback.
"""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor
from app.core.db import SessionDep
from app.core.idempotency import IdempotencyDep
from app.core.permissions import Perm, Principal, require
from app.core.schemas import StrictIn
from app.modules.booking_engine import api as engine
from app.modules.booking_engine.dto import (
    Actor,
    CounterBlockIn,
    CounterOrderIn,
    CounterOrderOut,
    CustomerSnapshot,
    ItemOut,
)
from app.modules.members import api as members
from app.modules.members.api import CustomerIn

router = APIRouter(prefix="/front-desk", tags=["front-desk"])

CounterBooker = Annotated[Principal, Depends(require(Perm.BOOKING_COUNTER_CREATE))]
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
        return await engine.create_counter_order(
            session, actor_of(principal), data.to_order(), snapshot, note
        )

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
        return await engine.register_ticket(session, actor_of(principal), code, snapshot, note)

    return await idem.run(session, principal.key, run, status_code=status.HTTP_201_CREATED)
