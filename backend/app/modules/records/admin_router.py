"""Màn "Kỷ lục & video" của Admin (T-046): danh sách số đo, gắn / sửa / gỡ link video.

T-047: nhập tay (duyệt ngay), sửa / xóa (trừ số đo máy đo), duyệt / từ chối bản hội viên gửi.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Path, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor
from app.core.db import SessionDep
from app.core.idempotency import Idempotency, IdempotencyDep
from app.core.middleware import require_origin
from app.core.permissions import Perm, Principal, require
from app.modules.member_inbox import api as inbox
from app.modules.records import admin, manual
from app.modules.records.schemas import (
    AdminSpeedRecordList,
    AdminSpeedRecordRow,
    RejectIn,
    Source,
    SpeedRecordCreateIn,
    SpeedRecordPatchIn,
    Status,
    VideoIn,
)

router = APIRouter(prefix="/admin/speed-records", tags=["records"])

VideoManager = Annotated[Principal, Depends(require(Perm.RECORDS_VIDEO_MANAGE))]
RecordId = Annotated[int, Path(ge=1)]


WRITE = [Depends(require_origin)]


def _actor(p: Principal) -> AuditActor:
    return AuditActor(type=p.actor_type, id=p.actor_id, label=p.label)


async def _run(
    session: AsyncSession,
    idem: Idempotency,
    principal: Principal,
    fn: Callable[[], Awaitable[Any]],
    status_code: int = 200,
) -> Response:
    """``idem.run`` + phát event thông báo hội viên **sau commit** (duyệt / từ chối)."""
    try:
        response = await idem.run(session, principal.key, fn, status_code)
    except BaseException:
        inbox.discard_pending(session)
        raise
    await inbox.publish_created(session)
    return response


@router.get("", response_model=AdminSpeedRecordList)
async def list_speed_records(
    _: VideoManager,
    session: SessionDep,
    has_video: Annotated[bool | None, Query(description="true: có video · false: chưa có")] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    status: Annotated[Status | None, Query(description="T-047: pending = tab Chờ duyệt")] = None,
    source: Annotated[Source | None, Query(description="device · admin · member")] = None,
):
    """Số đo mới nhất trước (20 / trang) – tên thật + Mã HV, sân, video, nguồn, trạng thái
    (chỉ Admin). ``pending_count`` cho tab "Chờ duyệt (n)"."""
    return await admin.list_records(session, has_video, page, status=status, source=source)


@router.post("", response_model=AdminSpeedRecordRow, status_code=201, dependencies=WRITE)
async def create_speed_record(
    data: SpeedRecordCreateIn, principal: VideoManager, idem: IdempotencyDep, session: SessionDep
):
    """Admin nhập số đo (T-047) -> ``source=admin``, duyệt ngay (tính hạng / kỷ lục). Audit
    ``record.create_manual``. 422: E-REC-7 (Mã HV không có / không Hoạt động), E-REC-5 (thời điểm
    ở tương lai / quá 365 ngày), E-REC-6 (sân), E-REC-1 (link video)."""
    return await _run(
        session,
        idem,
        principal,
        lambda: manual.create(session, _actor(principal), data),
        status_code=201,
    )


@router.patch("/{record_id}", response_model=AdminSpeedRecordRow, dependencies=WRITE)
async def update_speed_record(
    record_id: RecordId,
    data: SpeedRecordPatchIn,
    principal: VideoManager,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Sửa km/h, thời điểm, sân, video (chỉ ô có gửi; null = bỏ sân / gỡ video) kèm ``version``.
    403 E-REC-2 (số đo máy đo) · 409 E-REC-3 (lệch ``version``) · 404. Audit ``record.update``."""
    return await _run(
        session, idem, principal, lambda: manual.update(session, _actor(principal), record_id, data)
    )


@router.delete("/{record_id}", status_code=204, dependencies=WRITE)
async def delete_speed_record(
    record_id: RecordId, principal: VideoManager, idem: IdempotencyDep, session: SessionDep
):
    """Xóa thật số đo Admin nhập / hội viên gửi (audit ``record.delete`` giữ giá trị cũ).
    403 E-REC-2 (số đo máy đo) · 404."""
    return await _run(
        session,
        idem,
        principal,
        lambda: manual.delete(session, _actor(principal), record_id),
        status_code=204,
    )


@router.post("/{record_id}/approve", response_model=AdminSpeedRecordRow, dependencies=WRITE)
async def approve_speed_record(
    record_id: RecordId, principal: VideoManager, idem: IdempotencyDep, session: SessionDep
):
    """Duyệt bản hội viên gửi -> tính hạng / kỷ lục; báo hội viên. 409 E-REC-4 (không còn chờ
    duyệt) · 404. Audit ``record.approve``."""
    return await _run(
        session, idem, principal, lambda: manual.approve(session, _actor(principal), record_id)
    )


@router.post("/{record_id}/reject", response_model=AdminSpeedRecordRow, dependencies=WRITE)
async def reject_speed_record(
    record_id: RecordId,
    data: RejectIn,
    principal: VideoManager,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Từ chối + lý do (bắt buộc, ≤ 200 ký tự – 422 E-REC-8); báo hội viên kèm lý do.
    409 E-REC-4 · 404. Audit ``record.reject``."""
    return await _run(
        session,
        idem,
        principal,
        lambda: manual.reject(session, _actor(principal), record_id, data.reason),
    )


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
