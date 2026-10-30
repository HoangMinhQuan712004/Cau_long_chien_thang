"""Hồ sơ màn Hội viên (T-014): tra theo ``ref``, dựng dòng, đếm lượt đặt, kiểm trùng SĐT."""

import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.modules.booking_engine import api as engine
from app.modules.members.models import Customer
from app.modules.members.schemas import MemberRow
from app.modules.members.service import member_phone_taken

CODE_RE = re.compile(r"^HV\d{4}$", re.IGNORECASE)
CODE_MAX = 9999
RECENT_LIMIT = 5


def ref_of(c: Customer) -> str:
    return c.member_code if c.kind == "member" else str(c.public_id)


def booking_refs(c: Customer) -> list[str]:
    """Booking tại quầy lưu id hồ sơ; booking online trước khi có hồ sơ lưu ``phone:<sđt>``."""
    return [str(c.id), f"phone:{c.phone}"]


def forbidden() -> AppError:
    return AppError("E-AUTH-2", "Không có quyền thực hiện thao tác này", 403)


def not_found() -> AppError:
    return AppError("E-NOT-FOUND", "Không tìm thấy hồ sơ.", 404)


async def bookings_of(session: AsyncSession, customers: list[Customer]) -> dict[int, int]:
    refs = [r for c in customers for r in booking_refs(c)]
    stats = await engine.customer_stats(session, refs)
    return {c.id: sum(stats[r].bookings for r in booking_refs(c) if r in stats) for c in customers}


def to_row(c: Customer, bookings: int) -> MemberRow:
    return MemberRow(
        ref=ref_of(c),
        kind=c.kind,
        member_code=c.member_code,
        full_name=c.full_name,
        phone=c.phone,
        gender=c.gender,
        tier=c.tier,
        racket=c.racket,
        is_active=c.is_active,
        bookings=bookings,
        created_at=c.created_at,
    )


async def by_ref(session: AsyncSession, ref: str, lock: bool = False) -> Customer:
    """Mã HV (không phân biệt hoa thường) hoặc mã tham chiếu hồ sơ tạm; không có -> 404."""
    if CODE_RE.match(ref):
        cond = Customer.member_code == ref.upper()
    else:
        try:
            cond = Customer.public_id == uuid.UUID(ref)
        except ValueError:
            raise not_found() from None
    stmt = select(Customer).where(cond)
    customer = await session.scalar(stmt.with_for_update() if lock else stmt)
    if customer is None:
        raise not_found()
    return customer


async def ensure_phone_free(session: AsyncSession, phone: str, own_id: int | None = None) -> None:
    """SĐT trùng hội viên -> E-018; trùng hồ sơ tạm -> E-MEM-1."""
    other = await session.scalar(select(Customer).where(Customer.phone == phone))
    if other is None or other.id == own_id:
        return
    if other.kind == "member":
        raise member_phone_taken(other, hint="")
    raise await temp_phone_taken(session, other)


async def temp_phone_taken(session: AsyncSession, temp: Customer) -> AppError:
    """E-MEM-1 kèm dữ liệu cho câu xác nhận "Nâng hồ sơ tạm thành hội viên?" của FE."""
    return AppError(
        "E-MEM-1",
        f"Số điện thoại này đã có hồ sơ tạm – {temp.full_name}.",
        409,
        ref=str(temp.public_id),
        full_name=temp.full_name,
        bookings=(await bookings_of(session, [temp]))[temp.id],
        next_code=await next_code(session),
    )


async def commit_or_conflict(
    session: AsyncSession, phone: str, own_id: int | None = None, *, flush_only: bool = False
) -> None:
    """Hai máy lưu cùng lúc: UNIQUE(phone / member_code) bắt -> trả lỗi trùng như kiểm trước."""
    try:
        await (session.flush() if flush_only else session.commit())
    except IntegrityError:
        await session.rollback()
        await ensure_phone_free(session, phone, own_id)
        raise AppError(
            "E-012", "Dữ liệu vừa được cập nhật ở máy khác. Vui lòng thử lại.", 409
        ) from None


async def next_code(session: AsyncSession) -> str:
    last = await session.scalar(select(func.max(Customer.member_code)))
    number = int(last[2:]) + 1 if last else 1
    if number > CODE_MAX:
        raise AppError("E-MEM-4", "Đã hết mã hội viên (HV9999).", 409)
    return f"HV{number:04d}"
