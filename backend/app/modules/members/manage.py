"""Ghi màn Hội viên (T-014, chỉnh T-020): thêm hội viên, sửa hồ sơ, tạo hồ sơ tạm.

Thêm hội viên / tạo hồ sơ tạm **không commit** – router chạy qua ``Idempotency.run`` (commit nghiệp
vụ cùng kết quả, gửi lại cùng key -> kết quả cũ – T-020 AC3). Sửa hồ sơ tự commit.
"""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.errors import AppError
from app.modules.auth import api as auth
from app.modules.members import rackets
from app.modules.members.models import Customer
from app.modules.members.profiles import (
    bookings_of,
    by_ref,
    commit_or_conflict,
    ensure_phone_free,
    forbidden,
    next_code,
    ref_of,
    stale,
    to_row,
)
from app.modules.members.schemas import (
    MemberCan,
    MemberCreateIn,
    MemberRow,
    MemberUpdateIn,
    TempCreateIn,
)
from app.modules.members.service import clean_name, clean_phone


async def _new_code(session: AsyncSession) -> str:
    """Cấp mã HV dưới khóa advisory (transaction) – hai máy lưu cùng lúc không trùng mã."""
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('member_code'))"))
    return await next_code(session)


async def create_member(
    session: AsyncSession, actor: AuditActor, data: MemberCreateIn
) -> MemberRow:
    """Thêm hội viên. SĐT đã thuộc hội viên -> E-018; đã có hồ sơ tạm -> E-MEM-1 (SRS E-004,
    T-020 AC1 – không nâng hồ sơ tạm). Không commit."""
    full_name, phone = clean_name(data.full_name), clean_phone(data.phone)
    await ensure_phone_free(session, phone)
    code = await _new_code(session)
    c = Customer(
        kind="member",
        member_code=code,
        full_name=full_name,
        phone=phone,
        gender=data.gender,
        tier=data.tier,
        racket=await rackets.ensure(session, data.racket, actor),
        is_active=True,
    )
    # Hội viên = khách có tài khoản đăng nhập (T-015), cùng transaction. Gọi TRƯỚC ``add``: câu
    # SELECT bên trong autoflush hồ sơ -> trùng SĐT nổ ngoài ``commit_or_conflict`` (500)
    await auth.ensure_customer_account(session, phone, full_name)
    session.add(c)
    audit(session, actor, "member.create", "customer", code, {"tier": data.tier})
    # Hai máy lưu cùng SĐT: UNIQUE bắt ở flush -> báo trùng như kiểm trước
    await commit_or_conflict(session, phone, flush_only=True)
    await session.refresh(c)
    return to_row(c, (await bookings_of(session, [c]))[c.id])


TEMP_FIELDS = {"full_name", "gender"}


async def update_profile(
    session: AsyncSession, actor: AuditActor, ref: str, data: MemberUpdateIn, can: MemberCan
) -> MemberRow:
    """Sửa hội viên (không đổi SĐT) hoặc hồ sơ tạm (chỉ họ tên, giới tính)."""
    c = await by_ref(session, ref, lock=True)
    if c.version != data.version:  # T-020 AC4: máy khác (hoặc hội viên tự sửa) vừa lưu
        raise stale()
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
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
        changes["racket"] = await rackets.ensure(session, changes["racket"], actor)
    changed = sorted(k for k, v in changes.items() if getattr(c, k) != v)
    for field in changed:
        setattr(c, field, changes[field])
    if changed:
        c.version += 1
    if "is_active" in changed:  # Ngừng -> khóa tài khoản khách cùng SĐT; Hoạt động -> mở (T-015)
        await auth.set_customer_account_active(session, c.phone, c.is_active)
    if changed:
        detail = {"fields": changed}
        detail.update({k: changes[k] for k in ("tier", "is_active") if k in changed})
        action = "member.update" if c.kind == "member" else "member.temp.update"
        audit(session, actor, action, "customer", ref_of(c), detail)
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
    audit(
        session, actor, "member.temp.create", "customer", str(c.public_id), {"full_name": full_name}
    )
    await session.refresh(c)
    return to_row(c, (await bookings_of(session, [c]))[c.id])
