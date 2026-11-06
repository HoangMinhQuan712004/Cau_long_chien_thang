"""Đọc màn Hội viên (T-014): danh sách lọc / phân trang, chi tiết + thống kê đặt sân.

Thống kê đọc qua mặt tiền booking engine (không JOIN chéo module), khớp theo ``customer_ref``.
"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.modules.booking_engine import api as engine
from app.modules.members import rackets
from app.modules.members.avatar import etag_of_customer
from app.modules.members.models import Customer, CustomerAvatar
from app.modules.members.profiles import (
    RECENT_LIMIT,
    booking_refs,
    bookings_of,
    by_ref,
    ref_of,
    to_row,
)
from app.modules.members.schemas import (
    MemberBooking,
    MemberCan,
    MemberCounts,
    MemberDetail,
    MemberListOut,
)
from app.modules.members.service import collapse_spaces, search_condition


def _filters(q: str | None, status: str | None, tier: str | None, racket: str | None) -> list:
    conds = []
    if q and q.strip():
        conds.append(search_condition(q))
    if status is not None:
        conds.append(Customer.is_active.is_(status == "active"))
    if tier == "none":
        conds.append(Customer.tier.is_(None))
    elif tier is not None:
        conds.append(Customer.tier == tier)
    if collapse_spaces(racket):
        # Theo tên (không theo id): vợt đã xóa khỏi danh mục vẫn lọc được
        conds.append(rackets.CUSTOMER_RACKET_KEY == rackets.key_of(racket))
    return conds


async def list_members(
    session: AsyncSession,
    can: MemberCan,
    *,
    q: str | None,
    kind: str | None,
    status: str | None,
    tier: str | None,
    racket: str | None,
    sort: str | None,
    page: int,
    size: int,
) -> MemberListOut:
    """Mặc định: hồ sơ thêm mới nhất trước (hội viên + hồ sơ tạm xếp chung; hồ sơ tạm được nâng
    giữ ngày tạo gốc). ``id`` phá hòa khi trùng thời điểm.

    ``sort=bookings[_desc]`` / ``bookings_asc``: theo số lượt; bằng lượt thì giữ thứ tự mặc định
    (mới nhất trước) – sort của Python ổn định nên phân trang không nhảy dòng.
    """
    conds = _filters(q, status, tier, racket)
    by_kind = dict(
        (
            await session.execute(
                select(Customer.kind, func.count()).where(*conds).group_by(Customer.kind)
            )
        ).all()
    )
    counts = MemberCounts(
        all=sum(by_kind.values()), member=by_kind.get("member", 0), temp=by_kind.get("temp", 0)
    )
    if kind is not None:
        conds.append(Customer.kind == kind)
    total = counts.all if kind is None else getattr(counts, kind)
    # Ảnh: chỉ lấy etag bằng join (một truy vấn, không tải bytes)
    stmt = (
        select(Customer, CustomerAvatar.etag)
        .outerjoin(CustomerAvatar, CustomerAvatar.customer_id == Customer.id)
        .where(*conds)
        .order_by(Customer.created_at.desc(), Customer.id.desc())
    )
    offset = (page - 1) * size
    if sort is not None:
        # Lượt đặt nằm ở engine (không JOIN chéo module): tính cho cả tập lọc rồi cắt trang
        rows = (await session.execute(stmt)).all()
        customers = [c for c, _ in rows]
        bookings = await bookings_of(session, customers)
        sign = 1 if sort == "bookings_asc" else -1
        customers.sort(key=lambda c: sign * bookings[c.id])
        customers = customers[offset : offset + size]
    else:
        rows = (await session.execute(stmt.offset(offset).limit(size))).all()
        customers = [c for c, _ in rows]
        bookings = await bookings_of(session, customers)
    etags = {c.id: etag for c, etag in rows}
    return MemberListOut(
        items=[to_row(c, bookings[c.id], etags[c.id]) for c in customers],
        total=total,
        page=page,
        size=size,
        counts=counts,
        can=can,
    )


async def get_detail(
    session: AsyncSession, actor: AuditActor, ref: str, can: MemberCan
) -> MemberDetail:
    """Chi tiết hồ sơ: ghi nhật ký ``member.view`` (không ghi SĐT)."""
    c = await by_ref(session, ref)
    refs = booking_refs(c)
    stats = await engine.customer_stats(session, refs)
    recent = await engine.customer_bookings(session, refs, RECENT_LIMIT)
    detail = MemberDetail(
        **to_row(
            c, sum(s.bookings for s in stats.values()), await etag_of_customer(session, c.id)
        ).model_dump(),
        note=c.note,
        total_minutes=sum(s.minutes for s in stats.values()),
        recent_bookings=[MemberBooking(**b.model_dump(exclude={"payment_status"})) for b in recent],
        can=can,
    )
    audit(session, actor, "member.view", "customer", ref_of(c), {"kind": c.kind})
    await session.commit()
    return detail
