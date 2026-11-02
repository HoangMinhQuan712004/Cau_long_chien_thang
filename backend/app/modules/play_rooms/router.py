"""Phòng chơi trong khu hội viên (T-017).

Chỉ hội viên có liên kết (``CurrentMember``). Lệnh ghi cần Origin + ``Idempotency-Key``; thao tác
trên trạng thái phòng gửi kèm ``version`` (cũ -> 409 E-ROOM-6, FE tải lại). Thông báo trong web
phát sự kiện ``member.notification_created`` sau commit.
"""

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, Path, Query, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionDep
from app.core.idempotency import IdempotencyDep
from app.core.middleware import require_origin
from app.modules.auth import api as auth
from app.modules.member_inbox import api as inbox
from app.modules.play_rooms import actions, history, matches, views
from app.modules.play_rooms import api as rooms_api
from app.modules.play_rooms import errors as room_errors
from app.modules.play_rooms.common import Me
from app.modules.play_rooms.models import PlayRoom
from app.modules.play_rooms.schemas import (
    Format,
    FormatIn,
    InviteIn,
    LineupIn,
    MatchList,
    PlayHistory,
    Ranking,
    ResultIn,
    RoomDetail,
    RoomList,
    RoomRef,
    VersionIn,
)

router = APIRouter(prefix="/member-area", tags=["member-area"])

RoomId = Annotated[int, Path(ge=1)]
WRITE = [Depends(require_origin)]


IfNoneMatch = Annotated[str | None, Header(description="ETag lần trước -> 304 nếu không đổi")]
NOT_MODIFIED = {304: {"description": "Không đổi so với ETag gửi lên (polling 5 giây, AC21)"}}


def _etag_response(body: BaseModel, if_none_match: str | None) -> Response:
    """ETag theo nội dung (theo người xem): trùng -> 304 không thân, tiết kiệm polling."""
    payload = jsonable_encoder(body)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    etag = f'W/"{hashlib.sha256(raw).hexdigest()[:32]}"'
    headers = {"ETag": etag, "Cache-Control": "no-cache, private"}
    if if_none_match is not None and etag in {t.strip() for t in if_none_match.split(",")}:
        return Response(status_code=304, headers=headers)
    return JSONResponse(payload, headers=headers)


def _me(member: auth.LinkedMember) -> Me:
    return Me(member.user_id, member.customer_id)


async def _run(
    session: AsyncSession,
    idem: IdempotencyDep,
    me: Me,
    action: Callable[[], Awaitable[PlayRoom]],
) -> Response:
    async def fn() -> RoomDetail:
        room = await action()
        return await views.detail_of(session, me, room)

    try:
        response = await idem.run(session, me.idem_key, fn)
    except BaseException:
        inbox.discard_pending(session)
        raise
    await inbox.publish_created(session)
    return response


# ------------------------------------------------------------------ đọc


@router.get("/rooms", response_model=RoomList, responses=NOT_MODIFIED)
async def list_rooms(
    member: auth.CurrentMember,
    session: SessionDep,
    if_none_match: IfNoneMatch = None,
    scope: Annotated[Literal["all", "mine"], Query(description="mine: phòng có mình")] = "all",
):
    """Danh sách sân hôm nay còn mở + số liệu banner (AC4–AC6). 403 E-HV-8 (chưa là hội viên)."""
    return _etag_response(await views.list_rooms(session, _me(member), scope), if_none_match)


@router.get("/rooms/by-booking/{code}", response_model=RoomRef)
async def room_by_booking(
    code: Annotated[str, Path(max_length=40, description="Mã con của khối booking")],
    member: auth.CurrentMember,
    session: SessionDep,
    response: Response,
):
    """Phòng của booking vừa đặt (nút "Vào phòng" ở trang thành công, T-018 AC5).

    Phòng do worker tạo sau khi tiền về (~2 giây): 404 khi chưa có hoặc mình không ở trong phòng
    -> FE thử lại mỗi 2 giây, tối đa ~20 giây.
    """
    response.headers["Cache-Control"] = "no-store"
    room_id = await rooms_api.room_id_for_booking(session, member.customer_id, code)
    if room_id is None:
        raise room_errors.not_found()
    return RoomRef(room_id=room_id)


@router.get("/rooms/{room_id}", response_model=RoomDetail, responses=NOT_MODIFIED)
async def get_room(
    room_id: RoomId,
    member: auth.CurrentMember,
    session: SessionDep,
    if_none_match: IfNoneMatch = None,
):
    """Chi tiết phòng (cả phòng đã đóng – chỉ xem). 404 nếu không có / Host chưa đủ điều kiện."""
    return _etag_response(await views.room_detail(session, _me(member), room_id), if_none_match)


# ------------------------------------------------------------------ xin vào / duyệt


@router.post("/rooms/{room_id}/join-requests", response_model=RoomDetail, dependencies=WRITE)
async def request_join(
    room_id: RoomId,
    data: VersionIn,
    member: auth.CurrentMember,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Xin vào (AC8). 409 E-ROOM-1/2/4/6 · 429 E-SEC-5 (> 10 lần / ngày)."""
    me = _me(member)
    return await _run(
        session, idem, me, lambda: actions.request_join(session, me, room_id, data.version)
    )


@router.delete("/rooms/{room_id}/join-requests/mine", response_model=RoomDetail, dependencies=WRITE)
async def cancel_join(
    room_id: RoomId, member: auth.CurrentMember, idem: IdempotencyDep, session: SessionDep
):
    """Hủy "Xin vào" của mình (không cần ``version``; chưa xin -> không đổi gì)."""
    me = _me(member)
    return await _run(session, idem, me, lambda: actions.cancel_join(session, me, room_id))


@router.post(
    "/rooms/{room_id}/join-requests/{request_id}/approve",
    response_model=RoomDetail,
    dependencies=WRITE,
)
async def approve_join(
    room_id: RoomId,
    request_id: Annotated[int, Path(ge=1)],
    data: VersionIn,
    member: auth.CurrentMember,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Host duyệt. 403 E-ROOM-7 · 409 E-ROOM-1/2/6."""
    me = _me(member)
    return await _run(
        session,
        idem,
        me,
        lambda: actions.decide_join(session, me, room_id, request_id, data.version, True),
    )


@router.post(
    "/rooms/{room_id}/join-requests/{request_id}/reject",
    response_model=RoomDetail,
    dependencies=WRITE,
)
async def reject_join(
    room_id: RoomId,
    request_id: Annotated[int, Path(ge=1)],
    data: VersionIn,
    member: auth.CurrentMember,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Host từ chối. 403 E-ROOM-7 · 409 E-ROOM-1/6."""
    me = _me(member)
    return await _run(
        session,
        idem,
        me,
        lambda: actions.decide_join(session, me, room_id, request_id, data.version, False),
    )


# ------------------------------------------------------------------ mời


@router.post(
    "/rooms/{room_id}/invites",
    response_model=RoomDetail,
    status_code=status.HTTP_200_OK,
    dependencies=WRITE,
)
async def invite(
    room_id: RoomId,
    data: InviteIn,
    member: auth.CurrentMember,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Host mời bằng SĐT đầy đủ (AC9). 422 E-ROOM-3 (một câu cho mọi lý do) · 409 E-ROOM-2/4/6 ·
    403 E-ROOM-7 · 429 E-SEC-5 (> 20 lần / giờ, tính cả lần lỗi)."""
    me = _me(member)
    return await _run(
        session, idem, me, lambda: actions.invite(session, me, room_id, data.phone, data.version)
    )


@router.post("/invites/{invite_id}/accept", response_model=RoomDetail, dependencies=WRITE)
async def accept_invite(
    invite_id: Annotated[int, Path(ge=1)],
    member: auth.CurrentMember,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Nhận lời mời -> vào phòng. 404 (không phải lời mời của mình) · 409 E-ROOM-1/2/6."""
    me = _me(member)
    return await _run(
        session, idem, me, lambda: actions.answer_invite(session, me, invite_id, True)
    )


@router.post("/invites/{invite_id}/decline", response_model=RoomDetail, dependencies=WRITE)
async def decline_invite(
    invite_id: Annotated[int, Path(ge=1)],
    member: auth.CurrentMember,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Từ chối lời mời. 404 · 409 E-ROOM-1/6."""
    me = _me(member)
    return await _run(
        session, idem, me, lambda: actions.answer_invite(session, me, invite_id, False)
    )


# ------------------------------------------------------------------ rời / mời ra / chuyển Host


@router.post("/rooms/{room_id}/leave", response_model=RoomDetail, dependencies=WRITE)
async def leave(
    room_id: RoomId,
    data: VersionIn,
    member: auth.CurrentMember,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Rời phòng (AC11). 409 E-ROOM-5 (đang trong trận) / E-ROOM-1 / E-ROOM-6."""
    me = _me(member)
    return await _run(session, idem, me, lambda: actions.leave(session, me, room_id, data.version))


@router.post(
    "/rooms/{room_id}/members/{member_id}/kick", response_model=RoomDetail, dependencies=WRITE
)
async def kick(
    room_id: RoomId,
    member_id: Annotated[int, Path(ge=1, description="Id dòng thành viên phòng")],
    data: VersionIn,
    member: auth.CurrentMember,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Host mời ra (AC12). 403 E-ROOM-7 · 404 · 409 E-ROOM-1/5/6."""
    me = _me(member)
    return await _run(
        session, idem, me, lambda: actions.kick(session, me, room_id, member_id, data.version)
    )


@router.post(
    "/rooms/{room_id}/members/{member_id}/transfer-host",
    response_model=RoomDetail,
    dependencies=WRITE,
)
async def transfer_host(
    room_id: RoomId,
    member_id: Annotated[int, Path(ge=1, description="Id dòng thành viên phòng")],
    data: VersionIn,
    member: auth.CurrentMember,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Host chuyển quyền (AC12). 403 E-ROOM-7 · 404 · 409 E-ROOM-1/6."""
    me = _me(member)
    return await _run(
        session,
        idem,
        me,
        lambda: actions.transfer_host(session, me, room_id, member_id, data.version),
    )


# ------------------------------------------------------------------ mốc 2: thể thức, bốc, trận


@router.put("/rooms/{room_id}/format", response_model=RoomDetail, dependencies=WRITE)
async def set_format(
    room_id: RoomId,
    data: FormatIn,
    member: auth.CurrentMember,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Đổi thể thức 2 vs 2 / 1 vs 1 (Host). Đã bốc -> xóa kết quả bốc. 409 E-ROOM-11 (đang chơi)."""
    me = _me(member)
    return await _run(
        session,
        idem,
        me,
        lambda: matches.set_format(session, me, room_id, data.format, data.version),
    )


@router.post("/rooms/{room_id}/draw", response_model=RoomDetail, dependencies=WRITE)
async def draw(
    room_id: RoomId,
    data: VersionIn,
    member: auth.CurrentMember,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Bốc ngẫu nhiên / Bốc lại từ Hàng chờ (Host, AC15). 409 E-ROOM-8 (chưa đủ) / E-ROOM-11."""
    me = _me(member)
    return await _run(session, idem, me, lambda: matches.draw(session, me, room_id, data.version))


@router.put("/rooms/{room_id}/lineup", response_model=RoomDetail, dependencies=WRITE)
async def set_lineup(
    room_id: RoomId,
    data: LineupIn,
    member: auth.CurrentMember,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Host tự xếp đội hình (T-027) -> trận ``drawn`` như kết quả bốc; ``team_a`` / ``team_b`` =
    id dòng thành viên phòng (``members[].id``). Lỗi: 422 E-ROOM-12 (không ở phòng, trùng, sai
    số người) · 403 E-ROOM-7 · 409 E-ROOM-11 (đang chơi) / E-ROOM-6 (version cũ) / E-ROOM-1."""
    me = _me(member)
    return await _run(
        session,
        idem,
        me,
        lambda: matches.set_lineup(session, me, room_id, data.team_a, data.team_b, data.version),
    )


@router.post("/rooms/{room_id}/start", response_model=RoomDetail, dependencies=WRITE)
async def start(
    room_id: RoomId,
    data: VersionIn,
    member: auth.CurrentMember,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Bắt đầu trận vừa bốc (Host, AC16). 409 E-ROOM-10 (sớm hơn 15 phút) / E-ROOM-8 (chưa bốc)."""
    me = _me(member)
    return await _run(session, idem, me, lambda: matches.start(session, me, room_id, data.version))


@router.post("/rooms/{room_id}/matches/{no}/result", response_model=RoomDetail, dependencies=WRITE)
async def save_result(
    room_id: RoomId,
    no: Annotated[int, Path(ge=1)],
    data: ResultIn,
    member: auth.CurrentMember,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Lưu tỉ số (Host, một lần, không sửa – AC17). 422 E-ROOM-9 · 409 E-ROOM-6 (đã lưu / cũ)."""
    me = _me(member)
    return await _run(
        session,
        idem,
        me,
        lambda: matches.save_result(
            session, me, room_id, no, data.score_a, data.score_b, data.version
        ),
    )


@router.get("/rooms/{room_id}/matches", response_model=MatchList, responses=NOT_MODIFIED)
async def match_list(
    room_id: RoomId,
    member: auth.CurrentMember,
    session: SessionDep,
    format: Format | None = None,
    if_none_match: IfNoneMatch = None,
):
    """Lịch sử trận đấu (AC19): đã lưu, mới nhất trên cùng; số đếm tính mọi thể thức."""
    body = await matches.match_list(session, _me(member), room_id, format)
    return _etag_response(body, if_none_match)


@router.get("/play-history", response_model=PlayHistory, responses=NOT_MODIFIED)
async def play_history(
    member: auth.CurrentMember,
    session: SessionDep,
    month: Annotated[
        str | None, Query(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM, mặc định tháng này")
    ] = None,
    if_none_match: IfNoneMatch = None,
):
    """Lịch sử chơi của mình theo tháng ngày chơi, giờ VN (T-029): buổi = phòng có ≥ 1 trận đã lưu
    mà mình ở đội A/B, kể cả phòng đã rời. Tháng sai -> 422; tháng tương lai -> rỗng."""
    body = await history.play_history(session, member.customer_id, month)
    return _etag_response(body, if_none_match)


@router.get("/rooms/{room_id}/ranking", response_model=Ranking, responses=NOT_MODIFIED)
async def ranking(
    room_id: RoomId,
    member: auth.CurrentMember,
    session: SessionDep,
    format: Format | None = None,
    if_none_match: IfNoneMatch = None,
):
    """Xếp hạng trong phòng (AC20)."""
    body = await matches.ranking(session, _me(member), room_id, format)
    return _etag_response(body, if_none_match)
