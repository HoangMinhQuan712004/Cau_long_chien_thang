"""Danh mục vợt (T-014 việc 11): đọc / thêm / sửa và tự thêm khi lưu hội viên.

``ensure`` **không commit** (cùng transaction với hồ sơ hội viên); hàm của Admin tự commit.
"""

from sqlalchemy import String, any_, bindparam, func, select
from sqlalchemy.dialects.postgresql import ARRAY, insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.errors import AppError
from app.modules.members.models import Customer, Racket
from app.modules.members.schemas import RacketCreateIn, RacketOut, RacketUpdateIn
from app.modules.members.service import clean_text, collapse_spaces

# Khóa tên vợt = gộp khoảng trắng + chữ thường. Hai dạng cùng công thức: ``key_of`` (Python) để
# ghi ``racket.name_key``, ``CUSTOMER_RACKET_KEY`` (SQL) để so cột ``customer.racket``.


def key_of(name: str | None) -> str:
    return collapse_spaces(name).lower()


CUSTOMER_RACKET_KEY = func.lower(func.btrim(func.regexp_replace(Customer.racket, r"\s+", " ", "g")))


def _valid_name(raw: str | None) -> str:
    return clean_text(raw, "tên vợt")


def validate_name(raw: str | None) -> str:
    """Kiểm tên vợt (độ dài…) mà không ghi gì – để báo lỗi cùng các ô khác (T-016)."""
    return _valid_name(raw)


def _taken(name: str) -> AppError:
    return AppError("E-MEM-5", f"Vợt “{name}” đã có trong danh mục.", 409)


async def ensure(session: AsyncSession, raw: str | None) -> str | None:
    """Tên vợt chuẩn cho hồ sơ: đã có (kể cả đang ẩn) -> tên trong danh mục; chưa có -> thêm.

    ``ON CONFLICT DO NOTHING``: hai máy cùng thêm một vợt mới -> dùng chung một dòng, không lỗi.
    """
    if not collapse_spaces(raw):
        return None
    name = _valid_name(raw)
    await session.execute(
        insert(Racket)
        .values(name=name, name_key=key_of(name))
        .on_conflict_do_nothing(index_elements=[Racket.name_key])
    )
    return await session.scalar(select(Racket.name).where(Racket.name_key == key_of(name)))


async def _with_counts(session: AsyncSession, items: list[Racket]) -> list[RacketOut]:
    """Gắn ``member_count`` bằng **một** query GROUP BY cho cả danh sách."""
    keys = [r.name_key for r in items]
    counts = (
        dict(
            (
                await session.execute(
                    select(CUSTOMER_RACKET_KEY, func.count())
                    .where(
                        CUSTOMER_RACKET_KEY == any_(bindparam("keys", keys, type_=ARRAY(String)))
                    )
                    .group_by(CUSTOMER_RACKET_KEY)
                )
            ).all()
        )
        if keys
        else {}
    )
    return [
        RacketOut(
            id=r.id,
            name=r.name,
            is_active=r.is_active,
            sort_order=r.sort_order,
            member_count=counts.get(r.name_key, 0),
        )
        for r in items
    ]


async def list_rackets(session: AsyncSession, include_hidden: bool) -> list[RacketOut]:
    stmt = select(Racket).order_by(Racket.sort_order, Racket.name)
    if not include_hidden:
        stmt = stmt.where(Racket.is_active.is_(True))
    return await _with_counts(session, list(await session.scalars(stmt)))


async def _get(session: AsyncSession, racket_id: int) -> Racket:
    racket = await session.get(Racket, racket_id, with_for_update=True)
    if racket is None:
        raise AppError("E-NOT-FOUND", "Không tìm thấy vợt.", 404)
    return racket


async def _commit(session: AsyncSession, name: str) -> None:
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise _taken(name) from None


async def create(session: AsyncSession, actor: AuditActor, data: RacketCreateIn) -> RacketOut:
    name = _valid_name(data.name)
    if await session.scalar(select(Racket.id).where(Racket.name_key == key_of(name))):
        raise _taken(name)
    racket = Racket(name=name, name_key=key_of(name), sort_order=data.sort_order)
    session.add(racket)
    audit(session, actor, "racket.create", "racket", None, {"name": name})
    await _commit(session, name)
    await session.refresh(racket)
    return (await _with_counts(session, [racket]))[0]


async def update(
    session: AsyncSession, actor: AuditActor, racket_id: int, data: RacketUpdateIn
) -> RacketOut:
    """Đổi tên / ẩn-hiện / thứ tự. Hồ sơ hội viên giữ tên cũ (lưu dạng chữ)."""
    racket = await _get(session, racket_id)
    changes = data.model_dump(exclude_unset=True)
    if any(changes.get(f, 0) is None for f in ("is_active", "sort_order")):
        raise AppError("E-001", "Giá trị không hợp lệ.", 422)
    if "name" in changes:
        name = _valid_name(changes.pop("name"))
        other = await session.scalar(select(Racket.id).where(Racket.name_key == key_of(name)))
        if other is not None and other != racket.id:
            raise _taken(name)
        changes |= {"name": name, "name_key": key_of(name)}
    changed = sorted(k for k, v in changes.items() if getattr(racket, k) != v)
    for field in changed:
        setattr(racket, field, changes[field])
    if changed:
        detail = {"fields": [f for f in changed if f != "name_key"], "name": racket.name}
        audit(session, actor, "racket.update", "racket", str(racket.id), detail)
    await _commit(session, racket.name)
    await session.refresh(racket)
    return (await _with_counts(session, [racket]))[0]


async def delete(session: AsyncSession, actor: AuditActor, racket_id: int) -> None:
    """Xóa hẳn khỏi danh mục; hồ sơ hội viên giữ tên vợt (lưu dạng chữ)."""
    racket = await _get(session, racket_id)
    audit(session, actor, "racket.delete", "racket", str(racket.id), {"name": racket.name})
    await session.delete(racket)
    await session.commit()
