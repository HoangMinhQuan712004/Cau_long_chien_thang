"""Thao tác ghi trên phòng (T-017 AC8–AC12) – không commit (router chạy qua ``Idempotency.run``).

Mọi thao tác khóa dòng phòng (``FOR UPDATE``) trước khi đếm người -> ≤ 8 người kể cả khi duyệt /
nhận lời cùng lúc (AC10). Đổi gì trên phòng thì ``version + 1`` (AC21).
"""

import secrets
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.audit import audit, audit_change, audit_detail
from app.modules.member_inbox import api as inbox
from app.modules.members import api as members
from app.modules.play_rooms import errors, tiers
from app.modules.play_rooms.common import (
    CAPACITY,
    Me,
    actor,
    eligible,
    is_closed,
    member_count,
    member_row,
    member_rows,
    name_of,
    release_player,
    room_label,
    room_link,
    touch,
    visible_room,
    writable_room,
)
from app.modules.play_rooms.lifecycle import close_room
from app.modules.play_rooms.models import PlayRoom, PlayRoomMember, PlayRoomRequest

JOIN_PER_DAY = 10  # yêu cầu xin vào / người / ngày (AC8)
INVITES_PER_HOUR = 20  # lời mời / Host / giờ – chống dò SĐT (AC9)


def _require_host(room: PlayRoom, me: Me) -> None:
    if room.host_customer_id != me.customer_id:
        raise errors.host_only()


async def _ensure_space(session: AsyncSession, room: PlayRoom) -> None:
    if await member_count(session, room.id) >= CAPACITY:
        raise errors.full()


def _add_member(session: AsyncSession, room: PlayRoom, customer_id: int, now: datetime) -> None:
    """Vào phòng = đứng cuối Hàng chờ (AC13)."""
    session.add(
        PlayRoomMember(room_id=room.id, customer_id=customer_id, waiting_since=now, joined_at=now)
    )


async def _close_pending(
    session: AsyncSession, room_id: int, customer_id: int, kind: str, status: str, now: datetime
) -> None:
    await session.execute(
        update(PlayRoomRequest)
        .where(
            PlayRoomRequest.room_id == room_id,
            PlayRoomRequest.customer_id == customer_id,
            PlayRoomRequest.kind == kind,
            PlayRoomRequest.status == "pending",
        )
        .values(status=status, decided_at=now)
    )


def _notify(session: AsyncSession, room: PlayRoom, customer_id: int, kind: str, text: str) -> None:
    inbox.notify(session, customer_id, kind, text, room_link(room.id), room_id=room.id)


async def _pending(
    session: AsyncSession, room_id: int, customer_id: int, kind: str
) -> PlayRoomRequest | None:
    return await session.scalar(
        select(PlayRoomRequest).where(
            PlayRoomRequest.room_id == room_id,
            PlayRoomRequest.customer_id == customer_id,
            PlayRoomRequest.kind == kind,
            PlayRoomRequest.status == "pending",
        )
    )


# ------------------------------------------------------------------ xin vào (AC8)


async def request_join(session: AsyncSession, me: Me, room_id: int, version: int) -> PlayRoom:
    now = datetime.now(UTC)
    room = await writable_room(session, room_id, version, now)
    if await member_row(session, room.id, me.customer_id) is not None:
        raise errors.already_in_room()
    await tiers.require(session, room, me.customer_id)
    await _ensure_space(session, room)
    if await _pending(session, room.id, me.customer_id, "join") is not None:
        return room  # đã xin – bấm lại không tạo thêm
    retry_after = await ratelimit.check("room.join", str(me.customer_id), JOIN_PER_DAY, 86400)
    if retry_after is not None:
        raise ratelimit.too_many(retry_after)
    session.add(PlayRoomRequest(room_id=room.id, customer_id=me.customer_id, kind="join"))
    touch(room)
    people = await members.room_people(session, {me.customer_id})
    _notify(
        session,
        room,
        room.host_customer_id,
        "room.join_requested",
        f"{name_of(people, me.customer_id)} xin vào phòng {room_label(room)}.",
    )
    await session.flush()
    return room


async def cancel_join(session: AsyncSession, me: Me, room_id: int) -> PlayRoom:
    """Hủy "Xin vào" của mình (không cần ``version`` – chỉ đụng yêu cầu của chính mình)."""
    now = datetime.now(UTC)
    room = await writable_room(session, room_id, None, now)
    req = await _pending(session, room.id, me.customer_id, "join")
    if req is not None:
        req.status, req.decided_at = "cancelled", now
        touch(room)
        await session.flush()
    return room


async def decide_join(
    session: AsyncSession, me: Me, room_id: int, request_id: int, version: int, approve: bool
) -> PlayRoom:
    """Host duyệt / từ chối. Duyệt khi đã 8 người -> E-ROOM-2."""
    now = datetime.now(UTC)
    room = await writable_room(session, room_id, version, now)
    _require_host(room, me)
    req = await session.scalar(
        select(PlayRoomRequest).where(
            PlayRoomRequest.id == request_id,
            PlayRoomRequest.room_id == room.id,
            PlayRoomRequest.kind == "join",
        )
    )
    if req is None:
        raise errors.not_found()
    if req.status != "pending":
        raise errors.stale()
    people = await members.room_people(session, {me.customer_id, req.customer_id})
    if approve and await member_row(session, room.id, req.customer_id) is None:
        await tiers.require(session, room, req.customer_id)
        await _ensure_space(session, room)
        _add_member(session, room, req.customer_id, now)
        await _close_pending(session, room.id, req.customer_id, "invite", "cancelled", now)
    req.status, req.decided_at = ("accepted" if approve else "rejected"), now
    touch(room)
    if approve:
        _notify(
            session,
            room,
            req.customer_id,
            "room.join_approved",
            f"Host đã duyệt bạn vào phòng {room_label(room)}.",
        )
        audit(
            session,
            actor(me, people),
            "room.join_approved",
            "play_room",
            str(room.id),
            audit_detail(
                room.booking_code,
                room_label(room),
                [audit_change("Thành viên", None, name_of(people, req.customer_id))],
                room_id=room.id,
                customer_id=req.customer_id,
            ),
        )
    else:
        _notify(
            session,
            room,
            req.customer_id,
            "room.join_rejected",
            f"Host đã từ chối yêu cầu vào phòng {room_label(room)}.",
        )
    await session.flush()
    return room


# ------------------------------------------------------------------ mời (AC9)


async def invite(session: AsyncSession, me: Me, room_id: int, phone: str, version: int) -> PlayRoom:
    """Host mời bằng SĐT đầy đủ. Một câu E-ROOM-3 cho mọi lý do không mời được (SEC2)."""
    retry_after = await ratelimit.check(
        "room.invite", str(me.customer_id), INVITES_PER_HOUR, 3600
    )  # đếm cả lần mời lỗi – chống dò SĐT
    if retry_after is not None:
        raise ratelimit.too_many(retry_after)
    now = datetime.now(UTC)
    room = await writable_room(session, room_id, version, now)
    _require_host(room, me)
    target = await members.member_id_by_phone(session, phone)
    if target is None or target not in await eligible(session, {target}):
        raise errors.no_member_account()
    if target == me.customer_id or await member_row(session, room.id, target) is not None:
        raise errors.already_in_room()
    await tiers.require(session, room, target)
    await _ensure_space(session, room)
    if await _pending(session, room.id, target, "invite") is not None:
        return room  # đã mời, đang chờ
    session.add(
        PlayRoomRequest(
            room_id=room.id, customer_id=target, kind="invite", invited_by=me.customer_id
        )
    )
    touch(room)
    people = await members.room_people(session, {me.customer_id})
    _notify(
        session,
        room,
        target,
        "room.invited",
        f"{name_of(people, me.customer_id)} mời bạn vào phòng {room_label(room)}.",
    )
    await session.flush()
    return room


async def _my_invite(session: AsyncSession, me: Me, invite_id: int) -> PlayRoomRequest:
    req = await session.scalar(
        select(PlayRoomRequest).where(
            PlayRoomRequest.id == invite_id,
            PlayRoomRequest.kind == "invite",
            PlayRoomRequest.customer_id == me.customer_id,
        )
    )
    if req is None:  # lời mời của người khác -> 404 (không lộ)
        raise errors.not_found()
    return req


async def answer_invite(session: AsyncSession, me: Me, invite_id: int, accept: bool) -> PlayRoom:
    """Nhận lời (vào phòng, kiểm 8 người) / từ chối lời mời của chính mình."""
    now = datetime.now(UTC)
    req = await _my_invite(session, me, invite_id)
    room = await visible_room(session, req.room_id, lock=True)
    await session.refresh(req)  # đọc lại sau khi đã khóa phòng
    if is_closed(room, now):
        raise errors.closed()
    if req.status != "pending":
        raise errors.stale()
    if accept and await member_row(session, room.id, me.customer_id) is None:
        await tiers.require(session, room, me.customer_id)
        await _ensure_space(session, room)
        _add_member(session, room, me.customer_id, now)
        await _close_pending(session, room.id, me.customer_id, "join", "cancelled", now)
    req.status, req.decided_at = ("accepted" if accept else "rejected"), now
    touch(room)
    await session.flush()
    return room


# ------------------------------------------------------------------ rời, mời ra, chuyển Host


async def _hand_over(
    session: AsyncSession, room: PlayRoom, new_host: int, me: Me, reason: str
) -> None:
    old = room.host_customer_id
    room.host_customer_id = new_host
    people = await members.room_people(session, {old, new_host, me.customer_id})
    _notify(
        session,
        room,
        new_host,
        "room.host_assigned",
        f"Bạn đã trở thành Host phòng {room_label(room)}.",
    )
    audit(
        session,
        actor(me, people),
        "room.host_transferred",
        "play_room",
        str(room.id),
        audit_detail(
            room.booking_code,
            room_label(room),
            [audit_change("Host", name_of(people, old), name_of(people, new_host))],
            room_id=room.id,
            reason=reason,
        ),
    )


async def leave(session: AsyncSession, me: Me, room_id: int, version: int) -> PlayRoom:
    """Rời phòng. Host rời -> Host mới ngẫu nhiên; không còn ai -> phòng đóng (AC11)."""
    now = datetime.now(UTC)
    room = await writable_room(session, room_id, version, now)
    row = await member_row(session, room.id, me.customer_id)
    if row is None:
        raise errors.stale()
    await release_player(session, room.id, me.customer_id, me=True)
    await session.delete(row)
    await session.flush()
    touch(room)
    if room.host_customer_id == me.customer_id:
        rest = await member_rows(session, room.id)
        if not rest:
            await close_room(session, room, now)
        else:
            # Ưu tiên người còn đủ điều kiện làm Host (hội viên Hoạt động có liên kết)
            ok = await eligible(session, {m.customer_id for m in rest})
            pool = [m.customer_id for m in rest if m.customer_id in ok] or [
                m.customer_id for m in rest
            ]
            await _hand_over(session, room, secrets.choice(pool), me, reason="host_left")
    await session.flush()
    return room


async def _target(session: AsyncSession, room: PlayRoom, me: Me, member_id: int) -> PlayRoomMember:
    row = await session.get(PlayRoomMember, member_id)
    if row is None or row.room_id != room.id or row.customer_id == me.customer_id:
        raise errors.not_found()
    return row


async def kick(
    session: AsyncSession, me: Me, room_id: int, member_id: int, version: int
) -> PlayRoom:
    """Host mời ra (AC12). Người đang chơi -> E-ROOM-5. Người bị mời ra có thể xin vào lại."""
    now = datetime.now(UTC)
    room = await writable_room(session, room_id, version, now)
    _require_host(room, me)
    row = await _target(session, room, me, member_id)
    await release_player(session, room.id, row.customer_id, me=False)
    kicked = row.customer_id
    people = await members.room_people(session, {me.customer_id, kicked})
    await session.delete(row)
    touch(room)
    _notify(
        session,
        room,
        kicked,
        "room.kicked",
        f"Bạn đã được mời ra khỏi phòng {room_label(room)}.",
    )
    audit(
        session,
        actor(me, people),
        "room.kicked",
        "play_room",
        str(room.id),
        audit_detail(
            room.booking_code,
            room_label(room),
            [audit_change("Thành viên", name_of(people, kicked), None)],
            room_id=room.id,
            customer_id=kicked,
        ),
    )
    await session.flush()
    return room


async def transfer_host(
    session: AsyncSession, me: Me, room_id: int, member_id: int, version: int
) -> PlayRoom:
    now = datetime.now(UTC)
    room = await writable_room(session, room_id, version, now)
    _require_host(room, me)
    row = await _target(session, room, me, member_id)
    touch(room)
    await _hand_over(session, room, row.customer_id, me, reason="transfer")
    await session.flush()
    return room


__all__ = [
    "answer_invite",
    "cancel_join",
    "decide_join",
    "invite",
    "kick",
    "leave",
    "request_join",
    "transfer_host",
]
