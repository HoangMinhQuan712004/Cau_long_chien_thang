"""Nghiệp vụ quầy (đặc thù dự án): ghép Hội viên + Booking engine (T-006 §1).

Snapshot khách luôn dựng ở **server** từ hồ sơ Hội viên (ADR-004 S8) – client chỉ gửi mã hội viên
hoặc thông tin hồ sơ tạm. Hồ sơ tạm + booking/vé nằm trong **một transaction** (``idem.run``):
cùng commit hoặc cùng rollback.
"""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor
from app.core.db import SessionDep
from app.core.idempotency import IdempotencyDep
from app.core.permissions import Perm, Principal, require
from app.core.schemas import StrictIn
from app.modules.booking_engine import api as engine
from app.modules.booking_engine.dto import Actor, CounterBookingIn, CustomerSnapshot, ItemOut
from app.modules.members import api as members
from app.modules.members.api import CustomerIn

router = APIRouter(prefix="/front-desk", tags=["front-desk"])

CounterBooker = Annotated[Principal, Depends(require(Perm.BOOKING_COUNTER_CREATE))]


class FrontDeskBookingIn(StrictIn):
    resource_code: str = Field(max_length=10)
    date: dt.date
    start_hour: int = Field(ge=0, le=23)
    end_hour: int = Field(ge=1, le=24)
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


@router.post("/bookings", response_model=ItemOut, status_code=status.HTTP_201_CREATED)
async def create_booking(
    data: FrontDeskBookingIn,
    principal: CounterBooker,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Đặt sân tại quầy: 1 sân, hôm nay, khung liền nhau -> booking Chưa thanh toán.

    Lỗi: E-001/E-002 (hồ sơ tạm), E-014 (không có hội viên), E-018 (SĐT là của hội viên),
    E-004 (khung đã qua), E-CFG-10 (khung không bán), E-019 (thiếu giá), E-003 (vừa có người đặt),
    403 (ngày khác hôm nay).
    """

    async def run() -> ItemOut:
        snapshot, note = await customer_snapshot(session, data.customer, principal)
        booking = CounterBookingIn(
            resource_code=data.resource_code,
            date=data.date,
            start_hour=data.start_hour,
            end_hour=data.end_hour,
        )
        return await engine.create_counter_booking(
            session, actor_of(principal), booking, snapshot, note
        )

    return await idem.run(session, principal.key, run, status_code=status.HTTP_201_CREATED)
