"""Theo dõi sân (T-069): khu quản trị, chỉ đọc, quyền ``play_rooms.monitor``.

Màn hôm nay tự tải lại mỗi 10 giây: gửi ``If-None-Match`` -> 304 khi không đổi (như API phòng).
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.core.db import SessionDep
from app.core.permissions import Perm, Principal, require
from app.modules.play_rooms import monitor
from app.modules.play_rooms.router import NOT_MODIFIED, IfNoneMatch, _etag_response
from app.modules.play_rooms.schemas import MonitorDay, MonitorRoomDetail

router = APIRouter(prefix="/play-rooms/admin", tags=["admin: play rooms"])

Monitor = Annotated[Principal, Depends(require(Perm.PLAY_ROOMS_MONITOR))]


@router.get("/day", response_model=MonitorDay, responses=NOT_MODIFIED)
async def monitor_day(
    _: Monitor,
    session: SessionDep,
    if_none_match: IfNoneMatch = None,
    date: Annotated[
        str | None, Query(description="YYYY-MM-DD, mặc định hôm nay (giờ VN); trong ±1 năm")
    ] = None,
):
    """Mỗi sân một hàng, các phòng của ngày theo giờ: trạng thái, Host, số người, trận đang đánh /
    trận gần nhất kèm tỉ số. Tên thật + biệt danh + mã HV (không SĐT; ẩn danh không áp). 422 E-001
    (ngày sai / ngoài ±1 năm) · 403."""
    return _etag_response(await monitor.day_view(session, date), if_none_match)


@router.get("/rooms/{room_id}", response_model=MonitorRoomDetail, responses=NOT_MODIFIED)
async def monitor_room(
    room_id: Annotated[int, Path(ge=1)],
    _: Monitor,
    session: SessionDep,
    if_none_match: IfNoneMatch = None,
):
    """Chi tiết phòng chỉ đọc: thành viên, mọi trận, bảng xếp hạng. Xem được mọi phòng, kể cả đã
    kết thúc / booking đã hủy (quy tắc T-054 không áp). 404 E-NOT-FOUND · 403."""
    return _etag_response(await monitor.room_view(session, room_id), if_none_match)
