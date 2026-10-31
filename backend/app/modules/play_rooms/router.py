"""Phòng chơi trong khu hội viên (T-017).

Chỉ hội viên có liên kết (``CurrentMember``). Lệnh ghi cần Origin + ``Idempotency-Key``; thao tác
trên trạng thái phòng gửi kèm ``version`` (cũ -> 409 E-ROOM-6, FE tải lại). Thông báo trong web
phát sự kiện ``member.notification_created`` sau commit.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import SessionDep
from app.core.idempotency import IdempotencyDep
from app.core.middleware import require_origin
from app.modules.auth import api as auth
from app.modules.member_inbox import api as inbox
from app.modules.play_rooms import actions, views
from app.modules.play_rooms.common import Me
from app.modules.play_rooms.models import PlayRoom
from app.modules.play_rooms.schemas import InviteIn, RoomDetail, RoomList, VersionIn

router = APIRouter(prefix="/member-area", tags=["member-area"])

RoomId = Annotated[int, Path(ge=1)]
WRITE = [Depends(require_origin)]


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


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


@router.get("/rooms", response_model=RoomList, dependencies=[Depends(no_store)])
async def list_rooms(
    member: auth.CurrentMember,
    session: SessionDep,
    scope: Annotated[Literal["all", "mine"], Query(description="mine: phòng có mình")] = "all",
):
    """Danh sách sân hôm nay còn mở + số liệu banner (AC4–AC6). 403 E-HV-8 (chưa là hội viên)."""
    return await views.list_rooms(session, _me(member), scope)


@router.get("/rooms/{room_id}", response_model=RoomDetail, dependencies=[Depends(no_store)])
async def get_room(room_id: RoomId, member: auth.CurrentMember, session: SessionDep):
    """Chi tiết phòng (cả phòng đã đóng – chỉ xem). 404 nếu không có / Host chưa đủ điều kiện."""
    return await views.room_detail(session, _me(member), room_id)


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
