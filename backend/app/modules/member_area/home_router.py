"""Tổng quan + Lịch sử thanh toán khu hội viên (T-018) – theo phiên, ``no-store``."""

import hashlib
import json
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Path, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, RootModel

from app.core.db import SessionDep
from app.modules.auth import api as auth
from app.modules.member_area import home
from app.modules.member_area.home_schemas import (
    EventCard,
    Overview,
    PaymentItem,
    PaymentList,
)

router = APIRouter(prefix="/member-area", tags=["member-area"])


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


class _EventList(RootModel[list[EventCard]]):
    pass


def _etag_response(body: BaseModel, if_none_match: str | None) -> Response:
    """ETag theo nội dung (theo người xem): trùng -> 304 không thân (T-036, như phòng chơi)."""
    payload = jsonable_encoder(body)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    etag = f'W/"{hashlib.sha256(raw).hexdigest()[:32]}"'
    headers = {"ETag": etag, "Cache-Control": "no-cache, private"}
    if if_none_match is not None and etag in {t.strip() for t in if_none_match.split(",")}:
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)


@router.get(
    "/overview",
    response_model=Overview,
    responses={304: {"description": "Không đổi so với ETag gửi lên"}},
)
async def overview(
    member: auth.CurrentMember,
    session: SessionDep,
    if_none_match: Annotated[str | None, Header()] = None,
):
    """Trang Tổng quan v2 (T-018 + T-036): chào, lịch hôm nay / sắp tới, thông báo chưa đọc, số
    liệu tháng, kỷ lục, phòng đang trống, hạng tháng, kỷ lục mới của cụm. ETag / 304.
    403 E-HV-8 (chưa là hội viên)."""
    body = await home.overview(session, member.customer_id, member.user_id)
    return _etag_response(body, if_none_match)


@router.get(
    "/events",
    response_model=list[EventCard],
    responses={304: {"description": "Không đổi so với ETag gửi lên"}},
)
async def upcoming_events(
    member: auth.CurrentMember,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=31, description="Số ngày tới (giờ VN)")] = 14,
    if_none_match: Annotated[str | None, Header()] = None,
):
    """Sự kiện sắp tới (T-045): chưa bắt đầu, ngày diễn ra từ hôm nay tới hôm nay + ``days``, sắp
    theo giờ bắt đầu. Có số chỗ (tính cả ghế đang giữ), ``can_buy`` + ``reason``, số vé của mình;
    không có danh sách người mua. Đặt vé: luồng T-023 (``/web/booking/event-checkouts``)."""
    body = await home.events(session, member.customer_id, days)
    return _etag_response(_EventList(body), if_none_match)


@router.get("/payments", response_model=PaymentList, dependencies=[Depends(no_store)])
async def payments(
    member: auth.CurrentMember,
    session: SessionDep,
    month: Annotated[
        str | None, Query(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM, mặc định tháng này")
    ] = None,
    kind: Annotated[Literal["all", "booking", "ticket"], Query()] = "all",
):
    """Các khoản **đã thanh toán** (booking + vé) theo tháng thanh toán, giờ VN (AC7–AC10)."""
    return await home.payments(session, member.customer_id, month, kind)


@router.get("/payments/{code}", response_model=PaymentItem, dependencies=[Depends(no_store)])
async def payment(
    code: Annotated[str, Path(max_length=40, description="``code`` của dòng (id nội bộ)")],
    member: auth.CurrentMember,
    session: SessionDep,
):
    """Chi tiết một khoản đã thanh toán của mình; khác -> 404 E-NOT-FOUND."""
    return await home.payment(session, member.customer_id, code)
