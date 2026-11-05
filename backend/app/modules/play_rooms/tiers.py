"""Khoảng hạng của phòng (T-031): ai ngoài khoảng / chưa xếp hạng không vào được phòng có giới hạn.

So hạng theo thứ tự ``TIERS`` qua ``members.api.tier_rank`` (không so chuỗi). Kiểm khi vào phòng
(xin vào, mời, duyệt, nhận lời); người đã ở trong phòng không bị đẩy ra khi hạng đổi.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.members import api as members
from app.modules.play_rooms import errors
from app.modules.play_rooms.models import PlayRoom
from app.modules.play_rooms.schemas import JoinBlock, TierRange


def has_range(room: PlayRoom) -> bool:
    return room.min_tier is not None or room.max_tier is not None


def range_out(room: PlayRoom) -> TierRange | None:
    return TierRange(min=room.min_tier, max=room.max_tier) if has_range(room) else None


def range_text(room: PlayRoom) -> str:
    """Câu khoảng hạng: Khá–Bán chuyên / từ Khá trở lên / đến Trung bình."""
    if room.min_tier and room.max_tier:
        return f"{room.min_tier}–{room.max_tier}"
    if room.min_tier:
        return f"từ {room.min_tier} trở lên"
    return f"đến {room.max_tier}"


def block_of(room: PlayRoom, person: members.RoomPerson | None) -> JoinBlock | None:
    """Lý do người này không vào được phòng vì hạng; None = vào được (hoặc phòng mở)."""
    if not has_range(room):
        return None
    rank = members.tier_rank(person.tier if person else None)
    if rank is None:
        return "unranked"
    low = members.tier_rank(room.min_tier)
    high = members.tier_rank(room.max_tier)
    if (low is not None and rank < low) or (high is not None and rank > high):
        return "out_of_range"
    return None


async def require(session: AsyncSession, room: PlayRoom, customer_id: int) -> None:
    """409 E-ROOM-13 khi người này không vào được phòng vì hạng (câu lỗi không nói hạng của họ)."""
    if not has_range(room):
        return
    people = await members.room_people(session, {customer_id})
    block = block_of(room, people.get(customer_id))
    if block is not None:
        raise errors.tier_blocked(range_text(room), unranked=block == "unranked")


def valid_range(min_tier: str | None, max_tier: str | None) -> bool:
    """Tên hạng hợp lệ (hoặc None) và ``min ≤ max`` khi có cả hai."""
    low, high = members.tier_rank(min_tier), members.tier_rank(max_tier)
    if (min_tier is not None and low is None) or (max_tier is not None and high is None):
        return False
    return low is None or high is None or low <= high
