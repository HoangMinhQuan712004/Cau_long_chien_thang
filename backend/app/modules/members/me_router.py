"""Khách xem hồ sơ hội viên của chính mình (T-015) – theo SĐT tài khoản, không nhận ref / SĐT."""

from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionDep
from app.modules.auth.api import MemberCardPhone
from app.modules.booking_engine import api as engine
from app.modules.members.models import Customer
from app.modules.members.profiles import booking_refs, not_found
from app.modules.members.schemas import MemberBooking, MyBookingsOut, MyMemberOut

router = APIRouter(prefix="/me/member", tags=["members"])

PAGE_SIZE = 10


async def _my_member(session: AsyncSession, phone: str) -> Customer:
    """Hồ sơ **hội viên** cùng SĐT; hồ sơ tạm / không có -> 404 (nghiệp vụ #7)."""
    c = await session.scalar(
        select(Customer).where(Customer.phone == phone, Customer.kind == "member")
    )
    if c is None:
        raise not_found()
    return c


@router.get("", response_model=MyMemberOut)
async def my_member(phone: MemberCardPhone, session: SessionDep):
    """Thẻ Hội viên. 401 · 403 E-AUTH-25 (chưa đổi MK) / E-AUTH-29 (cần xác minh SĐT) · 404."""
    c = await _my_member(session, phone)
    stats = await engine.customer_stats(session, booking_refs(c))
    return MyMemberOut(
        member_code=c.member_code,
        full_name=c.full_name,
        tier=c.tier,
        is_active=c.is_active,
        gender=c.gender,
        racket=c.racket,
        created_at=c.created_at,
        bookings=sum(s.bookings for s in stats.values()),
        total_minutes=sum(s.minutes for s in stats.values()),
    )


@router.get("/bookings", response_model=MyBookingsOut)
async def my_bookings(
    phone: MemberCardPhone, session: SessionDep, page: Annotated[int, Query(ge=1)] = 1
):
    """Lịch sử đặt sân, mới nhất trước, 10 dòng / trang. Lỗi như ``GET /me/member``."""
    refs = booking_refs(await _my_member(session, phone))
    stats = await engine.customer_stats(session, refs)
    rows = await engine.customer_bookings(session, refs, PAGE_SIZE, (page - 1) * PAGE_SIZE)
    return MyBookingsOut(
        items=[
            MemberBooking(
                **b.model_dump(exclude={"payment_status"}),
                is_cancelled=b.payment_status == "cancelled",
            )
            for b in rows
        ],
        total=sum(s.listed for s in stats.values()),
        page=page,
        size=PAGE_SIZE,
    )
