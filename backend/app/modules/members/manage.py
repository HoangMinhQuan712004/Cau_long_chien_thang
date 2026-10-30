"""Ghi màn Hội viên (T-014): thêm hội viên (kể cả nâng hồ sơ tạm), sửa hồ sơ, tạo hồ sơ tạm.

Hàm ở đây **tự commit** (khác ``service.py`` – phần đó gộp transaction với booking).
"""

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.errors import AppError
from app.modules.auth import api as auth
from app.modules.members import rackets
from app.modules.members.audit_fields import member_detail, snapshot, temp_detail
from app.modules.members.models import Customer
from app.modules.members.profiles import (
    bookings_of,
    by_ref,
    commit_or_conflict,
    ensure_phone_free,
    forbidden,
    next_code,
    ref_of,
    temp_phone_taken,
    to_row,
)
from app.modules.members.schemas import (
    MemberCan,
    MemberCreateIn,
    MemberRow,
    MemberUpdateIn,
    TempCreateIn,
)
from app.modules.members.service import clean_name, clean_phone, member_phone_taken


async def _new_code(session: AsyncSession) -> str:
    """Cấp mã HV dưới khóa advisory (transaction) – hai máy lưu cùng lúc không trùng mã."""
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('member_code'))"))
    return await next_code(session)


async def create_member(
    session: AsyncSession, actor: AuditActor, data: MemberCreateIn
) -> MemberRow:
    """Thêm hội viên; SĐT đang là hồ sơ tạm -> E-MEM-1, hoặc nâng hồ sơ đó (``upgrade_temp``)."""
    full_name, phone = clean_name(data.full_name), clean_phone(data.phone)
    # Khóa dòng: hai máy cùng nâng một hồ sơ tạm -> máy sau đọc lại thấy đã là hội viên
    existing = await session.scalar(
        select(Customer).where(Customer.phone == phone).with_for_update()
    )
    if existing is not None and existing.kind == "member":
        if data.upgrade_temp:
            raise AppError("E-MEM-3", f"Hồ sơ này đã là hội viên {existing.member_code}.", 409)
        raise member_phone_taken(existing, hint="")
    if existing is not None:
        if not data.upgrade_temp:
            raise await temp_phone_taken(session, existing)
        return await _upgrade_temp(session, actor, existing, full_name, data)
    code = await _new_code(session)
    c = Customer(
        kind="member",
        member_code=code,
        full_name=full_name,
        phone=phone,
        gender=data.gender,
        tier=data.tier,
        racket=await rackets.ensure(session, data.racket),
        is_active=True,
    )
    # Hội viên = khách có tài khoản đăng nhập (T-015), cùng transaction. Gọi TRƯỚC ``add``: câu
    # SELECT bên trong autoflush hồ sơ -> trùng SĐT nổ ngoài ``commit_or_conflict`` (500)
    await auth.ensure_customer_account(session, phone, full_name)
    session.add(c)
    audit(session, actor, "member.create", "customer", code, member_detail(c))
    await commit_or_conflict(session, phone)
    await session.refresh(c)
    return to_row(c, (await bookings_of(session, [c]))[c.id])


async def _upgrade_temp(
    session: AsyncSession, actor: AuditActor, c: Customer, full_name: str, data: MemberCreateIn
) -> MemberRow:
    """Hồ sơ tạm (đã khóa) -> hội viên trên **cùng dòng**: id + SĐT giữ nguyên nên lịch sử còn."""
    bookings = (await bookings_of(session, [c]))[c.id]
    before = snapshot(c)
    code = await _new_code(session)
    c.kind, c.member_code, c.tier = "member", code, data.tier
    c.full_name, c.gender = full_name, data.gender
    c.racket, c.is_active = await rackets.ensure(session, data.racket), True
    await auth.ensure_customer_account(session, c.phone, full_name)
    await auth.set_customer_account_active(session, c.phone, True)
    audit(
        session,
        actor,
        "member.promote",
        "customer",
        code,
        member_detail(c, before, bookings=bookings, ref=str(c.public_id)),
    )
    await session.commit()  # mã HV cấp dưới khóa advisory, SĐT không đổi -> không có xung đột
    await session.refresh(c)
    return to_row(c, bookings)


TEMP_FIELDS = {"full_name", "gender"}


async def update_profile(
    session: AsyncSession, actor: AuditActor, ref: str, data: MemberUpdateIn, can: MemberCan
) -> MemberRow:
    """Sửa hội viên (không đổi SĐT) hoặc hồ sơ tạm (chỉ họ tên, giới tính)."""
    c = await by_ref(session, ref, lock=True)
    changes = data.model_dump(exclude_unset=True)
    if c.kind == "temp" and set(changes) - TEMP_FIELDS:
        raise AppError("E-MEM-6", "Hồ sơ tạm chỉ sửa được họ tên và giới tính.", 422)
    if "is_active" in changes:
        if changes["is_active"] is None:
            raise AppError("E-001", "Giá trị không hợp lệ.", 422)
        if changes["is_active"] != c.is_active and not can.edit_status:
            raise forbidden()
    if "full_name" in changes:
        changes["full_name"] = clean_name(changes["full_name"] or "")
    if "racket" in changes:
        changes["racket"] = await rackets.ensure(session, changes["racket"])
    before = snapshot(c)
    changed = sorted(k for k, v in changes.items() if getattr(c, k) != v)
    for field in changed:
        setattr(c, field, changes[field])
    if "is_active" in changed:  # Ngừng -> khóa tài khoản khách cùng SĐT; Hoạt động -> mở (T-015)
        await auth.set_customer_account_active(session, c.phone, c.is_active)
    if changed:
        action = "member.update" if c.kind == "member" else "member.temp.update"
        audit(session, actor, action, "customer", ref_of(c), member_detail(c, before))
    await session.commit()  # SĐT không đổi -> không có xung đột UNIQUE
    await session.refresh(c)
    return to_row(c, (await bookings_of(session, [c]))[c.id])


async def create_temp(session: AsyncSession, actor: AuditActor, data: TempCreateIn) -> MemberRow:
    full_name, phone = clean_name(data.full_name), clean_phone(data.phone)
    await ensure_phone_free(session, phone)
    c = Customer(kind="temp", full_name=full_name, phone=phone, gender=data.gender, is_active=True)
    session.add(c)
    # flush trước để có public_id (server default) ghi vào nhật ký; trùng SĐT bắt ngay ở đây
    await commit_or_conflict(session, phone, flush_only=True)
    detail = temp_detail(full_name, phone, data.gender)
    audit(session, actor, "member.temp.create", "customer", str(c.public_id), detail)
    await session.commit()
    await session.refresh(c)
    return to_row(c, (await bookings_of(session, [c]))[c.id])
