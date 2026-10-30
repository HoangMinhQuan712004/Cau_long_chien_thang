"""Xem và lọc Lịch sử thao tác (SRS Lịch sử thao tác FR-001, FR-002). Chỉ đọc."""

from datetime import date, datetime, time, timedelta
from typing import Any, cast

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.errors import AppError
from app.modules.audit_log import catalog
from app.modules.audit_log.schemas import (
    ActorKind,
    AuditCatalogOut,
    AuditChangeOut,
    AuditEntryOut,
    AuditGroupOut,
    AuditLogPageOut,
    AuditLogQuery,
    AuditOptionOut,
    AuditSort,
    AuditTargetOut,
)
from app.modules.auth.models import User

DEFAULT_DAYS = 7  # BR-012: 7 ngày gần nhất, tính cả hôm nay

# Chỉ thao tác ở trang quản trị + việc Hệ thống làm; actor "web" (khách online) không hiện (BR-002)
SHOWN_ACTORS: tuple[ActorKind, ...] = ("admin", "staff", "system")


def _today() -> date:
    return datetime.now(settings.tz).date()


def _min_date(today: date) -> date:
    """Ngày sớm nhất chọn được: cùng ngày năm trước (29/02 -> 28/02)."""
    try:
        return today.replace(year=today.year - 1)
    except ValueError:
        return today.replace(year=today.year - 1, day=28)


def get_catalog() -> AuditCatalogOut:
    today = _today()
    return AuditCatalogOut(
        groups=[
            AuditGroupOut(
                label=g.label,
                types=[AuditOptionOut(key=t.key, label=t.label) for t in g.types],
            )
            for g in catalog.GROUPS
        ],
        actors=[AuditOptionOut(key=k, label=v) for k, v in catalog.ACTORS.items()],
        min_date=_min_date(today),
        max_date=today,
    )


def _range(q: AuditLogQuery) -> tuple[date, date]:
    today = _today()
    date_to = q.date_to or today
    date_from = q.date_from or date_to - timedelta(days=DEFAULT_DAYS - 1)
    # Màn hình đã khóa ngày ngoài khoảng (BR-012); API vẫn chặn gọi thẳng
    if date_from > date_to or date_to > today or date_from < _min_date(today):
        raise AppError("E-AUDIT-1", "Khoảng thời gian không hợp lệ.", 422)
    return date_from, date_to


def _staff_name(label: str) -> str:
    """Nhãn chụp "NV007 · Nguyễn Văn An" (ADR-008 §2) -> "Nguyễn Văn An"."""
    code, sep, name = label.partition(" · ")
    return name if sep and " " not in code else label


async def _staff_codes(session: AsyncSession, rows: list[AuditLog]) -> dict[int, str]:
    """Mã NV theo ``actor_id`` cho cả trang – 1 truy vấn."""
    ids = {r.actor_id for r in rows if r.actor_type == "staff" and r.actor_id is not None}
    if not ids:
        return {}
    found = await session.execute(
        select(User.id, User.staff_code).where(User.id.in_(ids), User.staff_code.is_not(None))
    )
    return {uid: code for uid, code in found}


def _entry(row: AuditLog, staff_codes: dict[int, str]) -> AuditEntryOut:
    kind = cast(ActorKind, row.actor_type)  # đã lọc theo SHOWN_ACTORS
    is_staff = kind == "staff"
    detail: dict[str, Any] = row.detail or {}
    action_type = catalog.BY_ACTION[row.action]
    return AuditEntryOut(
        id=row.id,
        at=row.at,
        actor=kind,
        actor_label=catalog.ACTORS[kind],
        actor_name=_staff_name(row.actor_label) if is_staff else None,
        actor_code=staff_codes.get(row.actor_id) if is_staff and row.actor_id else None,
        action=action_type.key,
        action_label=action_type.label,
        target=_target(detail.get("target"), row.entity_code),
        changes=_changes(detail.get("changes")),
    )


# Dòng cũ / hỏng (ghi trước khi chuẩn hóa, sửa tay) không được làm 500 cả trang


def _target(raw: Any, entity_code: str | None) -> AuditTargetOut:
    """Đối tượng thiếu / sai kiểu -> chỉ còn mã của dòng."""
    try:
        return AuditTargetOut.model_validate(raw)
    except ValidationError:
        return AuditTargetOut(code=entity_code, name=None)


def _changes(raw: Any) -> list[AuditChangeOut]:
    """Phần tử thiếu field / before / after hoặc sai kiểu ({from, to, ...}, list...) -> bỏ."""
    if not isinstance(raw, list):
        return []
    changes = []
    for item in raw:
        try:
            changes.append(AuditChangeOut.model_validate(item))
        except ValidationError:
            continue
    return changes


def _order(sort: AuditSort | None) -> tuple:
    """BR-015 mới trước; id phụ giữ trang ổn định. ``at_asc``: lệch docs, người dùng duyệt."""
    if sort == "at_asc":
        return AuditLog.at.asc(), AuditLog.id.asc()
    return AuditLog.at.desc(), AuditLog.id.desc()


async def list_entries(session: AsyncSession, q: AuditLogQuery) -> AuditLogPageOut:
    if q.action is not None and q.action not in catalog.TYPES:
        raise AppError("E-AUDIT-2", "Loại thao tác không hợp lệ.", 422)
    date_from, date_to = _range(q)
    tz = settings.tz
    actor_types = (q.actor,) if q.actor else SHOWN_ACTORS
    where = (
        AuditLog.at >= datetime.combine(date_from, time.min, tz),
        AuditLog.at < datetime.combine(date_to + timedelta(days=1), time.min, tz),
        AuditLog.action.in_(catalog.actions_for(q.action)),
        AuditLog.actor_type.in_(actor_types),
    )
    total = await session.scalar(select(func.count()).select_from(AuditLog).where(*where)) or 0
    rows = list(
        await session.scalars(
            select(AuditLog)
            .where(*where)
            .order_by(*_order(q.sort))
            .offset((q.page - 1) * q.size)
            .limit(q.size)
        )
    )
    staff_codes = await _staff_codes(session, rows)
    return AuditLogPageOut(
        items=[_entry(r, staff_codes) for r in rows],
        total=total,
        page=q.page,
        page_size=q.size,
        date_from=date_from,
        date_to=date_to,
    )
