"""Xóa sân (ẩn, giữ lịch sử): hàng ``resource`` vẫn còn để đơn cũ, báo cáo, kỷ lục nối tên sân.

Hàm ở đây **không commit**. Khóa dòng sân + ``config_service.lock_live_resources`` ở mọi nơi tạo chỗ
chiếm -> không lọt lịch mới giữa lúc kiểm và xóa. Phòng chơi luôn gắn với một booking nên đã được
đếm qua chỗ chiếm (engine không đọc bảng của ``play_rooms``).
"""

from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit, audit_change, audit_detail
from app.core.errors import AppError
from app.modules.booking_engine import occupancy, outbox
from app.modules.booking_engine.audit_fields import active_label
from app.modules.booking_engine.common import audit_actor
from app.modules.booking_engine.config_service import _resource_by_code
from app.modules.booking_engine.dto import Actor, OccupiedSlot
from app.modules.booking_engine.holds import hold_visible
from app.modules.booking_engine.models import Allocation, Hold
from app.modules.booking_engine.tenant import get_tenant, resource_label, tz_of


async def _unfinished(
    session: AsyncSession, tenant_id: int, resource_id: int, now: datetime, tz
) -> list[OccupiedSlot]:
    """Booking / sự kiện (kể cả vé) / giữ chỗ còn hiệu lực chưa kết thúc; đang diễn ra cũng tính."""
    rows = await session.scalars(
        select(Allocation)
        .outerjoin(Hold, (Hold.id == Allocation.hold_id) & hold_visible(now))
        .where(
            Allocation.tenant_id == tenant_id,
            Allocation.resource_id == resource_id,
            Allocation.active.is_(True),
            func.upper(Allocation.time_range) > now,
            or_(Allocation.kind != "hold", Hold.id.is_not(None)),
        )
        .order_by(func.lower(Allocation.time_range))
    )
    return [occupancy.slot_of(row, tz) for row in rows]


async def delete_resource(session: AsyncSession, tenant_id: int, actor: Actor, code: str) -> None:
    """Không có / đã xóa -> 404; còn lịch chưa kết thúc -> 409 ``E-CFG-11`` kèm ``count``."""
    tenant = await get_tenant(session, tenant_id)
    label = resource_label(tenant)
    r = await _resource_by_code(session, tenant_id, code, for_update=True)
    now = datetime.now(UTC)
    busy = await _unfinished(session, tenant_id, r.id, now, tz_of(tenant))
    if busy:
        raise AppError(
            "E-CFG-11",
            f"{label.capitalize()} còn {len(busy)} lịch sắp tới, "
            "hãy đổi sân hoặc hủy các lịch này trước khi xóa.",
            409,
            count=len(busy),
            **occupancy.listing(busy),
        )
    change = audit_change("Trạng thái", active_label(r.is_active), "Đã xóa")
    r.deleted_at = now
    r.is_active = False  # mọi truy vấn lọc sân hoạt động tự loại sân này
    r.version += 1
    detail = audit_detail(r.code, r.name, [change])
    audit(session, audit_actor(actor), "config.resource.delete", "resource", r.code, detail)
    outbox.add_event(session, tenant_id, "config.resource.deleted", {"code": r.code})
    await session.flush()
