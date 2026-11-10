"""Đổi sân thủ công cho một booking (khối): cùng ngày, cùng giờ; giữ mã, giá đã chụp, tiền đã thu.

Sân đích: đang hoạt động, chưa xóa, mở cửa đủ khung. Trùng lịch do exclusion constraint chặn (không
tự kiểm); danh sách sân đích (``targets``) chỉ là gợi ý cùng phép kiểm. Hàm ở đây **không commit**.
Phòng chơi lưu bản chụp tên sân -> phát ``booking.moved`` để module phòng chơi cập nhật sau commit.
"""

from datetime import UTC, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit, audit_change, audit_detail
from app.core.errors import AppError
from app.modules.booking_engine import outbox
from app.modules.booking_engine.booking_service import movable_reason, normalize_code
from app.modules.booking_engine.common import (
    EXCLUSION_VIOLATION,
    STALE_ITEM,
    Ctx,
    audit_actor,
    context,
    not_found,
    sqlstate,
)
from app.modules.booking_engine.config_service import _resource_by_code, lock_live_resources
from app.modules.booking_engine.dto import Actor, ItemOut, MoveIn, MoveTarget
from app.modules.booking_engine.holds import hold_visible
from app.modules.booking_engine.models import (
    RESOURCE_LIVE,
    Allocation,
    Booking,
    EventSession,
    Hold,
    Resource,
    ResourceType,
    Ticket,
)
from app.modules.booking_engine.payment_service import view_of
from app.modules.booking_engine.schedules import Hours, effective_on, schedules_of


def _not_movable(message: str) -> AppError:
    return AppError("E-BOOK-6", message, 409)


async def _booking(session: AsyncSession, tenant_id: int, raw_code: str, lock: bool) -> Booking:
    """Chỉ booking; vé / sự kiện / giữ chỗ online -> 409 rõ ràng, mã lạ -> 404."""
    code = normalize_code(raw_code)
    stmt = select(Booking).where(Booking.tenant_id == tenant_id, Booking.code == code)
    b = await session.scalar(stmt.with_for_update() if lock else stmt)
    if b is not None:
        return b
    for model in (Ticket, EventSession, Hold):
        if await session.scalar(
            select(model.id).where(model.tenant_id == tenant_id, model.code == code)
        ):
            raise _not_movable("Đổi sân chỉ áp dụng cho booking (không cho vé, sự kiện, giữ chỗ).")
    raise not_found(f"booking {code}")


def _check_movable(b: Booking, ctx: Ctx) -> None:
    reason = movable_reason(b, ctx)
    if reason == "inactive":
        raise _not_movable("Booking đã hủy hoặc Không thu được, không đổi sân được.")
    if reason == "ended":
        raise _not_movable("Booking đã kết thúc, không đổi sân được.")


def _sells(schedules: dict, r: Resource, b: Booking, ctx: Ctx) -> bool:
    sched = effective_on(schedules.get(r.id, []), b.play_date)
    return sched is not None and Hours.of(sched).sells(
        ctx.minute_of(b.play_date, b.start_at), ctx.minute_of(b.play_date, b.end_at)
    )


async def targets(session: AsyncSession, tenant_id: int, code: str) -> list[MoveTarget]:
    """Sân đích còn trống cùng khung, theo thứ tự danh mục (gợi ý – lúc đổi constraint quyết)."""
    ctx = await context(session, tenant_id)
    b = await _booking(session, tenant_id, code, lock=False)
    _check_movable(b, ctx)
    rows = (
        await session.execute(
            select(Resource, ResourceType.name)
            .join(ResourceType, ResourceType.id == Resource.resource_type_id)
            .where(
                Resource.tenant_id == tenant_id,
                Resource.id != b.resource_id,
                Resource.is_active.is_(True),
                RESOURCE_LIVE,
            )
            .order_by(Resource.sort_order, Resource.code)
        )
    ).all()
    schedules = await schedules_of(session, tenant_id, [r.id for r, _ in rows])
    busy = set(
        await session.scalars(
            select(Allocation.resource_id)
            .outerjoin(Hold, (Hold.id == Allocation.hold_id) & hold_visible(ctx.now))
            .where(
                Allocation.tenant_id == tenant_id,
                Allocation.active.is_(True),
                Allocation.time_range.overlaps(Range(b.start_at, b.end_at, bounds="[)")),
                or_(Allocation.kind != "hold", Hold.id.is_not(None)),
            )
        )
    )
    return [
        MoveTarget(code=r.code, name=r.name, type_name=type_name)
        for r, type_name in rows
        if r.id not in busy and _sells(schedules, r, b, ctx)
    ]


async def move(
    session: AsyncSession, tenant_id: int, actor: Actor, code: str, data: MoveIn
) -> ItemOut:
    """Khóa booking + sân đích; đổi sân của chỗ chiếm và booking trong một transaction."""
    ctx = await context(session, tenant_id)
    b = await _booking(session, tenant_id, code, lock=True)
    _check_movable(b, ctx)
    if b.version != data.version:
        raise AppError("E-012", STALE_ITEM, 409)
    target = await _resource_by_code(session, tenant_id, data.resource_code)
    if target.id == b.resource_id:
        raise _not_movable("Booking đã ở sân này.")
    schedules = await schedules_of(session, tenant_id, [target.id])
    if not target.is_active or not _sells(schedules, target, b, ctx):
        raise AppError("E-BOOK-7", f"{target.name} không nhận đặt khung giờ này.", 422)
    await lock_live_resources(session, {target.id})
    source = await session.get(Resource, b.resource_id)
    try:
        async with session.begin_nested():
            await session.execute(
                update(Allocation)
                .where(Allocation.booking_id == b.id, Allocation.active.is_(True))
                .values(resource_id=target.id)
            )
    except IntegrityError as e:
        if sqlstate(e) == EXCLUSION_VIOLATION:
            raise AppError(
                "E-BOOK-8", f"{target.name} đã có lịch trong khung này. Chọn sân khác.", 409
            ) from None
        raise
    b.resource_id = target.id
    b.version += 1
    change = audit_change("Sân", source.name, target.name)
    detail = audit_detail(b.code, b.customer_name, [change], moved_at=datetime.now(UTC).isoformat())
    audit(session, audit_actor(actor), "booking.move", "booking", b.code, detail)
    type_name = await session.scalar(
        select(ResourceType.name).where(ResourceType.id == target.resource_type_id)
    )
    outbox.add_event(
        session,
        tenant_id,
        "booking.moved",
        {
            "code": b.code,
            "resource_code": target.code,
            "resource_name": target.name,
            "resource_type_name": type_name,
        },
    )
    return await view_of(session, ctx, b)
