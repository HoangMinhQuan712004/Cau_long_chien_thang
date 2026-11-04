"""Màn "Kỷ lục & video" của Admin (T-046): danh sách số đo, gắn / sửa / gỡ link video."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query

from app.core.audit import AuditActor
from app.core.db import SessionDep
from app.core.idempotency import IdempotencyDep
from app.core.middleware import require_origin
from app.core.permissions import Perm, Principal, require
from app.modules.records import admin
from app.modules.records.schemas import AdminSpeedRecordList, AdminSpeedRecordRow, VideoIn

router = APIRouter(prefix="/admin/speed-records", tags=["records"])

VideoManager = Annotated[Principal, Depends(require(Perm.RECORDS_VIDEO_MANAGE))]
RecordId = Annotated[int, Path(ge=1)]


def _actor(p: Principal) -> AuditActor:
    return AuditActor(type=p.actor_type, id=p.actor_id, label=p.label)


@router.get("", response_model=AdminSpeedRecordList)
async def list_speed_records(
    _: VideoManager,
    session: SessionDep,
    has_video: Annotated[bool | None, Query(description="true: có video · false: chưa có")] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
):
    """Số đo mới nhất trước (20 / trang) – tên thật + Mã HV, sân, video (chỉ Admin)."""
    return await admin.list_records(session, has_video, page)


@router.put(
    "/{record_id}/video", response_model=AdminSpeedRecordRow, dependencies=[Depends(require_origin)]
)
async def set_video(
    record_id: RecordId,
    data: VideoIn,
    principal: VideoManager,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Gắn / sửa link video. Chỉ YouTube hoặc file .mp4 / .webm (https), khác -> 422 E-REC-1.
    Audit ``record.video_set``. Không có số đo -> 404."""
    return await idem.run(
        session,
        principal.key,
        lambda: admin.set_video(session, _actor(principal), record_id, data.url),
    )


@router.delete(
    "/{record_id}/video", response_model=AdminSpeedRecordRow, dependencies=[Depends(require_origin)]
)
async def remove_video(
    record_id: RecordId, principal: VideoManager, idem: IdempotencyDep, session: SessionDep
):
    """Gỡ video (audit ``record.video_removed``); chưa có video -> trả nguyên trạng."""
    return await idem.run(
        session, principal.key, lambda: admin.remove_video(session, _actor(principal), record_id)
    )
