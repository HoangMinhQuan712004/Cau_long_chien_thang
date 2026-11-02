"""Lưới đặt sân của hội viên (T-023): ô sân của mình + chi tiết đơn của mình – theo phiên.

Mua vé sự kiện dùng chung ``/web/booking/events/{code}`` và ``/web/booking/event-checkouts``
(``as_member``) với trang công khai (T-023 sửa đổi 02/11 b).
"""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.db import SessionDep
from app.core.ratelimit import rate_limit
from app.modules.auth import api as auth
from app.modules.booking_engine import api as engine
from app.modules.booking_engine.dto import MemberCalendarResource, MemberOrder
from app.modules.members import api as members
from app.modules.payments import api as payments

router = APIRouter(prefix="/member-area", tags=["member-area"])


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


class MemberCalendarOut(BaseModel):
    """Như ``WebCalendarOut``; mỗi ô thêm ``mine`` / ``order_code`` (chỉ ô của mình) /
    ``has_ticket``. Ô của người khác vẫn chỉ ``state = booked``."""

    date: dt.date
    server_now: dt.datetime
    online_enabled: bool = Field(description="Cùng điều kiện với /web/booking/calendar")
    hold_minutes: int
    columns: list[int]
    resources: list[MemberCalendarResource]


@router.get(
    "/booking-calendar",
    response_model=MemberCalendarOut,
    dependencies=[Depends(rate_limit("web.calendar", 60)), Depends(no_store)],
)
async def booking_calendar(
    member: auth.CurrentMember,
    session: SessionDep,
    day: Annotated[dt.date, Query(alias="date")],
):
    """Lịch /hoi-vien/dat-san (AC1, AC6). Ngày đã qua -> 422 E-WEB-2; chưa là hội viên -> 403."""
    refs = await members.booking_refs_of(session, member.customer_id)
    cal = await engine.member_calendar(session, day, refs)
    online = auth.otp_channel_ready() and await payments.online_enabled(session)
    return MemberCalendarOut(
        **cal.model_dump(), online_enabled=online, hold_minutes=settings.ONLINE_HOLD_MINUTES
    )


@router.get("/bookings/{order_code}", response_model=MemberOrder, dependencies=[Depends(no_store)])
async def my_booking(
    order_code: Annotated[str, Path(max_length=40)],
    member: auth.CurrentMember,
    session: SessionDep,
):
    """Đơn đặt sân của chính mình (AC2). ``items[].code`` dùng gọi ``/member-area/payments/{code}``
    (hóa đơn – khối đã thanh toán). Không có / của người khác -> 404 E-NOT-FOUND (AC4)."""
    refs = await members.booking_refs_of(session, member.customer_id)
    return await engine.member_order(session, refs, order_code)
