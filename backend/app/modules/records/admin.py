"""Admin gắn / sửa / gỡ video cho số đo tốc độ (T-046). Hàm ghi **không commit**.

T-047: dòng có nguồn / trạng thái / ``version``; lọc theo ``status`` / ``source``; nhập tay, sửa,
xóa, duyệt ở ``manual``.
"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit, audit_change, audit_detail
from app.core.errors import AppError
from app.modules.booking_engine import api as engine
from app.modules.members import api as members
from app.modules.records import video
from app.modules.records.models import SpeedRecord
from app.modules.records.schemas import (
    AdminSpeedRecordList,
    AdminSpeedRecordRow,
    Source,
    Status,
)

PAGE_SIZE = 20


def _not_found() -> AppError:
    return AppError("E-NOT-FOUND", "Không tìm thấy số đo.", 404)


async def _court_names(session: AsyncSession) -> dict[str, str]:
    return {r.code: r.name for r in (await engine.list_resources(session)).items}


async def rows_of(session: AsyncSession, records: list[SpeedRecord]) -> list[AdminSpeedRecordRow]:
    people = await members.room_people(session, {r.customer_id for r in records})
    courts = await _court_names(session) if any(r.court_code for r in records) else {}
    return [
        AdminSpeedRecordRow(
            id=r.id,
            speed_kmh=r.speed_kmh,
            measured_at=r.measured_at,
            member_code=people[r.customer_id].member_code if r.customer_id in people else None,
            member_name=people[r.customer_id].display_name if r.customer_id in people else "—",
            resource_code=r.court_code,
            resource_name=courts.get(r.court_code) if r.court_code else None,
            video=video.parse(r.video_url),
            source=r.source,  # type: ignore[arg-type]
            status=r.status,  # type: ignore[arg-type]
            reject_reason=r.reject_reason,
            editable=r.source != "device",
            submitted_at=r.created_at,
            version=r.version,
        )
        for r in records
    ]


async def pending_count(session: AsyncSession) -> int:
    count = select(func.count()).select_from(SpeedRecord).where(SpeedRecord.status == "pending")
    return await session.scalar(count) or 0


async def list_records(
    session: AsyncSession,
    has_video: bool | None,
    page: int,
    size: int = PAGE_SIZE,
    status: Status | None = None,
    source: Source | None = None,
) -> AdminSpeedRecordList:
    """Số đo mới nhất trước; Admin thấy tên thật (không áp ẩn danh), mọi trạng thái."""
    conds = []
    if status is not None:
        conds.append(SpeedRecord.status == status)
    if source is not None:
        conds.append(SpeedRecord.source == source)
    if has_video is True:
        conds.append(SpeedRecord.video_url.is_not(None))
    elif has_video is False:
        conds.append(SpeedRecord.video_url.is_(None))
    total = await session.scalar(select(func.count()).select_from(SpeedRecord).where(*conds)) or 0
    records = list(
        await session.scalars(
            select(SpeedRecord)
            .where(*conds)
            .order_by(SpeedRecord.measured_at.desc(), SpeedRecord.id.desc())
            .offset((page - 1) * size)
            .limit(size)
        )
    )
    return AdminSpeedRecordList(
        items=await rows_of(session, records),
        page=page,
        size=size,
        total=total,
        pending_count=await pending_count(session),
    )


def touch(r: SpeedRecord) -> None:
    """Mỗi lần đổi số đo: ``version`` +1 (PATCH chống ghi đè, T-047)."""
    r.updated_at = datetime.now(UTC)
    r.version += 1


async def locked(session: AsyncSession, record_id: int) -> SpeedRecord:
    r = await session.scalar(
        select(SpeedRecord).where(SpeedRecord.id == record_id).with_for_update()
    )
    if r is None:
        raise _not_found()
    return r


async def _audit(
    session: AsyncSession, actor: AuditActor, action: str, r: SpeedRecord, before, after
) -> None:
    people = await members.room_people(session, {r.customer_id})
    p = people.get(r.customer_id)
    code = p.member_code if p else None
    audit(
        session,
        actor,
        action,
        "speed_record",
        str(r.id),
        audit_detail(
            code,
            p.display_name if p else None,
            [audit_change("Video", before, after)],
            speed_kmh=r.speed_kmh,
            measured_at=r.measured_at.isoformat(),
            member_code=code,
        ),
    )


async def set_video(
    session: AsyncSession, actor: AuditActor, record_id: int, url: str
) -> AdminSpeedRecordRow:
    """Gắn / sửa link (422 E-REC-1 khi sai). Cùng link -> không ghi gì."""
    clean = video.clean(url)
    r = await locked(session, record_id)
    if r.video_url != clean:
        before = r.video_url
        r.set_video(clean, datetime.now(UTC))
        touch(r)
        await _audit(session, actor, "record.video_set", r, before, clean)
        await session.flush()
    return (await rows_of(session, [r]))[0]


async def remove_video(
    session: AsyncSession, actor: AuditActor, record_id: int
) -> AdminSpeedRecordRow:
    """Gỡ video; chưa có video -> trả nguyên trạng, không ghi nhật ký."""
    r = await locked(session, record_id)
    if r.video_url is not None:
        before = r.video_url
        r.set_video(None, datetime.now(UTC))
        touch(r)
        await _audit(session, actor, "record.video_removed", r, before, None)
        await session.flush()
    return (await rows_of(session, [r]))[0]
