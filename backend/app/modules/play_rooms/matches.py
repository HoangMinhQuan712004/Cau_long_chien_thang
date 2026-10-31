"""Bốc, chơi, nhập tỉ số (T-017 AC13–AC18) và Lịch sử trận / Xếp hạng trong một phòng (AC19, AC20).

Thao tác ghi không commit (router chạy qua ``Idempotency.run``), khóa dòng phòng, ``version + 1``.
"""

import secrets
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit, audit_change, audit_detail
from app.modules.members import api as members
from app.modules.play_rooms import errors
from app.modules.play_rooms.common import (
    START_EARLY,
    Me,
    active_match,
    actor,
    avatar_url,
    member_rows,
    name_of,
    room_label,
    touch,
    visible_room,
    writable_room,
)
from app.modules.play_rooms.models import PlayMatch, PlayRoom
from app.modules.play_rooms.schemas import MatchList, MatchRow, Ranking, RankingRow

PLAYERS = {"2v2": 4, "1v1": 2}
_rng = secrets.SystemRandom()  # CSPRNG (AC15)


def _require_host(room: PlayRoom, me: Me) -> None:
    if room.host_customer_id != me.customer_id:
        raise errors.host_only()


# ------------------------------------------------------------------ thuật toán bốc (AC15)


@dataclass(frozen=True)
class Waiting:
    customer_id: int
    waiting_since: datetime


def pick(waiting: list[Waiting], k: int, fresh: bool) -> list[int]:
    """Chọn ``k`` người từ Hàng chờ.

    - ``fresh`` (phòng chưa có trận nào bắt đầu – mọi người coi như cùng mốc): ngẫu nhiên hoàn toàn.
    - Còn lại: lấy người chờ lâu nhất (``waiting_since`` nhỏ nhất); nếu tại người thứ ``k`` có
      nhiều người **cùng mốc** thì bốc ngẫu nhiên trong nhóm cùng mốc đó.
    """
    if len(waiting) < k:
        raise errors.not_enough_players()
    if fresh:
        return [w.customer_id for w in _rng.sample(waiting, k)]
    ordered = sorted(waiting, key=lambda w: w.waiting_since)
    cutoff = ordered[k - 1].waiting_since
    sure = [w.customer_id for w in ordered if w.waiting_since < cutoff]
    tied = [w.customer_id for w in ordered if w.waiting_since == cutoff]
    return sure + _rng.sample(tied, k - len(sure))


def split_teams(chosen: list[int]) -> tuple[list[int], list[int]]:
    """Chia đội ngẫu nhiên (CSPRNG)."""
    shuffled = list(chosen)
    _rng.shuffle(shuffled)
    half = len(shuffled) // 2
    return shuffled[:half], shuffled[half:]


async def _ever_started(session: AsyncSession, room_id: int) -> bool:
    return bool(
        await session.scalar(
            select(func.count()).where(
                PlayMatch.room_id == room_id, PlayMatch.started_at.is_not(None)
            )
        )
    )


async def _next_no(session: AsyncSession, room_id: int) -> int:
    last = await session.scalar(select(func.max(PlayMatch.no)).where(PlayMatch.room_id == room_id))
    return (last or 0) + 1


# ------------------------------------------------------------------ thể thức, bốc, bắt đầu


async def set_format(
    session: AsyncSession, me: Me, room_id: int, fmt: str, version: int
) -> PlayRoom:
    """Đổi thể thức (Host). Đã bốc -> xóa kết quả bốc; đang chơi -> E-ROOM-11 (thể thức khóa)."""
    now = datetime.now(UTC)
    room = await writable_room(session, room_id, version, now)
    _require_host(room, me)
    if fmt == room.format:
        return room
    match = await active_match(session, room.id)
    if match is not None:
        if match.status == "playing":
            raise errors.match_in_progress(match.no)
        await session.delete(match)
    room.format = fmt
    touch(room)
    await session.flush()
    return room


async def draw(session: AsyncSession, me: Me, room_id: int, version: int) -> PlayRoom:
    """Bốc ngẫu nhiên / Bốc lại (Host, bất cứ lúc nào phòng mở – chốt Q7)."""
    now = datetime.now(UTC)
    room = await writable_room(session, room_id, version, now)
    _require_host(room, me)
    match = await active_match(session, room.id)
    if match is not None and match.status == "playing":
        raise errors.match_in_progress(match.no)
    waiting = [
        Waiting(m.customer_id, m.waiting_since)
        for m in await member_rows(session, room.id)
        if m.queue_state == "waiting"
    ]
    chosen = pick(waiting, PLAYERS[room.format], fresh=not await _ever_started(session, room.id))
    team_a, team_b = split_teams(chosen)
    people = await members.room_people(session, chosen)
    names = {str(cid): name_of(people, cid) for cid in chosen}
    if match is None:
        match = PlayMatch(room_id=room.id, no=await _next_no(session, room.id))
        session.add(match)
    match.format, match.team_a, match.team_b, match.names = room.format, team_a, team_b, names
    match.status, match.drawn_at = "drawn", now
    touch(room)
    await session.flush()
    return room


async def start(session: AsyncSession, me: Me, room_id: int, version: int) -> PlayRoom:
    """Bắt đầu trận #n (Host): từ 15 phút trước giờ chơi; người được bốc sang Đang chơi."""
    now = datetime.now(UTC)
    room = await writable_room(session, room_id, version, now)
    _require_host(room, me)
    match = await active_match(session, room.id)
    if match is None:
        raise errors.not_enough_players()  # chưa bốc
    if match.status == "playing":
        raise errors.match_in_progress(match.no)
    if now < room.start_at - START_EARLY:
        raise errors.too_early()
    match.status, match.started_at = "playing", now
    for m in await member_rows(session, room.id):
        if m.customer_id in (*match.team_a, *match.team_b):
            m.queue_state = "playing"
    touch(room)
    await session.flush()
    return room


async def save_result(
    session: AsyncSession, me: Me, room_id: int, no: int, score_a: int, score_b: int, version: int
) -> PlayRoom:
    """Lưu tỉ số trận đang chơi (Host, một lần – không có đường sửa). Người chơi về cuối Hàng chờ.

    Gửi lại cùng ``Idempotency-Key`` -> kết quả cũ (lớp router); khác key khi trận đã lưu ->
    E-ROOM-6 (``version`` đã đổi / trận không còn ``playing``).
    """
    if not (0 <= score_a <= 99 and 0 <= score_b <= 99) or score_a == score_b:
        raise errors.bad_score()
    now = datetime.now(UTC)
    room = await writable_room(session, room_id, version, now)
    _require_host(room, me)
    match = await active_match(session, room.id)
    if match is None or match.no != no or match.status != "playing":
        raise errors.stale()
    match.score_a, match.score_b = score_a, score_b
    match.winner = "a" if score_a > score_b else "b"
    match.status, match.ended_at = "finished", now
    players = {*match.team_a, *match.team_b}
    for m in await member_rows(session, room.id):
        if m.customer_id in players:
            m.queue_state, m.waiting_since = "waiting", now  # về cuối Hàng chờ (AC17)
    touch(room)
    people = await members.room_people(session, {me.customer_id})

    def team(ids: list[int]) -> str:
        return ", ".join(str(match.names.get(str(c), "Hội viên")) for c in ids)

    audit(
        session,
        actor(me, people),
        "room.match_saved",
        "play_room",
        str(room.id),
        audit_detail(
            room.booking_code,
            room_label(room),
            [audit_change(f"Trận #{match.no}", None, f"Đội A {score_a} – {score_b} Đội B")],
            room_id=room.id,
            match_no=match.no,
            format=match.format,
            score_a=score_a,
            score_b=score_b,
            winner=match.winner,
            team_a=team(match.team_a),
            team_b=team(match.team_b),
        ),
    )
    await session.flush()
    return room


# ------------------------------------------------------------------ Lịch sử trận, Xếp hạng


async def _finished(session: AsyncSession, room_id: int, fmt: str | None) -> list[PlayMatch]:
    q = select(PlayMatch).where(PlayMatch.room_id == room_id, PlayMatch.status == "finished")
    if fmt is not None:
        q = q.where(PlayMatch.format == fmt)
    return list(await session.scalars(q.order_by(PlayMatch.ended_at.desc(), PlayMatch.no.desc())))


def _names(match: PlayMatch, ids: list[int]) -> list[str]:
    return [str(match.names.get(str(c), "Hội viên")) for c in ids]


async def match_list(session: AsyncSession, me: Me, room_id: int, fmt: str | None) -> MatchList:
    room = await visible_room(session, room_id, lock=False)
    every = await _finished(session, room.id, None)
    shown = [m for m in every if fmt is None or m.format == fmt]
    return MatchList(
        total=len(every),
        count_2v2=sum(m.format == "2v2" for m in every),
        count_1v1=sum(m.format == "1v1" for m in every),
        items=[
            MatchRow(
                no=m.no,
                format=m.format,  # type: ignore[arg-type]
                started_at=m.started_at,
                ended_at=m.ended_at,
                team_a=_names(m, m.team_a),
                team_b=_names(m, m.team_b),
                score_a=m.score_a or 0,
                score_b=m.score_b or 0,
                winner=m.winner,  # type: ignore[arg-type]
            )
            for m in shown
        ],
    )


async def ranking(session: AsyncSession, me: Me, room_id: int, fmt: str | None) -> Ranking:
    """Xếp theo số trận thắng, bằng nhau thì tỉ lệ thắng; đồng hạng khi bằng cả hai (AC20).

    Gom theo id hồ sơ – người đã rời / bị mời ra vẫn giữ kết quả, tên lấy từ trận gần nhất.
    """
    room = await visible_room(session, room_id, lock=False)
    wins: dict[int, int] = defaultdict(int)
    played: dict[int, int] = defaultdict(int)
    latest_name: dict[int, str] = {}
    for m in await _finished(session, room.id, fmt):  # mới nhất trước
        winners = m.team_a if m.winner == "a" else m.team_b
        for cid in (*m.team_a, *m.team_b):
            played[cid] += 1
            latest_name.setdefault(cid, str(m.names.get(str(cid), "Hội viên")))
        for cid in winners:
            wins[cid] += 1
    people = await members.room_people(session, set(played))

    def rate(cid: int) -> float:
        return round(wins[cid] / played[cid], 4)

    ordered = sorted(played, key=lambda c: (-wins[c], -rate(c), latest_name[c].casefold(), c))
    rows: list[RankingRow] = []
    for i, cid in enumerate(ordered):
        prev = rows[-1] if rows else None
        same = prev is not None and (prev.wins, prev.win_rate) == (wins[cid], rate(cid))
        rows.append(
            RankingRow(
                rank=prev.rank if same and prev else i + 1,
                display_name=latest_name[cid],
                avatar_url=avatar_url(people.get(cid)),
                wins=wins[cid],
                losses=played[cid] - wins[cid],
                played=played[cid],
                win_rate=rate(cid),
                is_me=cid == me.customer_id,
            )
        )
    return Ranking(items=rows)
