"""Bảng xếp hạng tốc độ cú đập của khu hội viên (T-030 giai đoạn A) – chỉ đọc.

T-047: hội viên gửi cú đập của mình (chờ Admin duyệt), xem / rút lại bản đã gửi.
"""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response

from app.core.config import settings
from app.core.db import SessionDep
from app.core.idempotency import IdempotencyDep
from app.core.middleware import require_origin
from app.modules.auth import api as auth
from app.modules.records import manual, service
from app.modules.records.schemas import (
    MySpeedRecord,
    MySpeedRecordList,
    Period,
    RecordVideoList,
    SpeedRanking,
    SpeedSubmitIn,
    VideoPeriod,
)

router = APIRouter(prefix="/member-area", tags=["member-area"])


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/speed-ranking", response_model=SpeedRanking, dependencies=[Depends(no_store)])
async def speed_ranking(
    member: auth.CurrentMember,
    session: SessionDep,
    period: Annotated[Period, Query()] = "month",
    day: Annotated[
        dt.date | None, Query(alias="date", description="Ngày bất kỳ trong kỳ, mặc định hôm nay")
    ] = None,
):
    """Top 10 cú đập nhanh nhất trong kỳ (tuần T2→CN / tháng / năm, giờ VN) + hạng của tôi.

    Mỗi hội viên lấy số đo cao nhất trong kỳ, bằng nhau thì ai đạt trước xếp trên. Chỉ hội viên
    Hoạt động có tài khoản liên kết. Tắt "Hiện trên kỷ lục" -> "Hội viên ẩn danh" (mình luôn thấy
    tên mình). Không trả id của người khác. ``period`` / ``date`` sai -> 422.
    """
    today = dt.datetime.now(settings.tz).date()
    return await service.ranking(session, member.customer_id, period, day or today)


@router.get("/record-videos", response_model=RecordVideoList, dependencies=[Depends(no_store)])
async def record_videos(
    member: auth.CurrentMember,
    session: SessionDep,
    period: Annotated[VideoPeriod, Query()] = "month",
    day: Annotated[
        dt.date | None, Query(alias="date", description="Ngày bất kỳ trong kỳ, mặc định hôm nay")
    ] = None,
):
    """Video & kỷ lục (T-046): số đo có video trong kỳ (tuần T2→CN / tháng / năm / mọi thời gian,
    giờ VN), mới nhất trước, tối đa 60. Ẩn danh như Bảng xếp hạng (video vẫn phát)."""
    today = dt.datetime.now(settings.tz).date()
    return await service.record_videos(session, member.customer_id, period, day or today)


# ------------------------------------------------------------------ hội viên gửi cú đập (T-047)

WRITE = [Depends(require_origin), Depends(no_store)]


def _me(member: auth.LinkedMember) -> manual.Submitter:
    return manual.Submitter(user_id=member.user_id, customer_id=member.customer_id)


@router.post("/speed-records", response_model=MySpeedRecord, status_code=201, dependencies=WRITE)
async def submit_speed_record(
    data: SpeedSubmitIn, member: auth.CurrentMember, idem: IdempotencyDep, session: SessionDep
):
    """Gửi cú đập của **chính mình** (km/h, thời điểm, sân, link video) -> "Chờ duyệt"; chưa tính
    hạng / kỷ lục tới khi Admin duyệt. Audit ``record.submit``.
    403 E-REC-7 (hội viên Ngừng) · 422 E-REC-5 / E-REC-6 / E-REC-1 · 429 E-SEC-5 (đã gửi 5 bản
    trong ngày giờ VN – mọi trạng thái, bản đã rút lại không tính; lượt lỗi không tính).
    """
    me = _me(member)
    return await idem.run(
        session, f"customer:{me.user_id}", lambda: manual.submit(session, me, data), 201
    )


@router.get(
    "/speed-records/mine", response_model=MySpeedRecordList, dependencies=[Depends(no_store)]
)
async def my_speed_records(member: auth.CurrentMember, session: SessionDep):
    """Bản tôi đã gửi (Chờ duyệt / Đã duyệt / Bị từ chối + lý do), mới gửi trước; kèm danh sách
    sân đang hoạt động cho hộp "Gửi cú đập". Không có bản của người khác."""
    return await manual.list_mine(session, member.customer_id)


@router.delete("/speed-records/{record_id}", status_code=204, dependencies=WRITE)
async def withdraw_speed_record(
    record_id: Annotated[int, Path(ge=1)],
    member: auth.CurrentMember,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Rút lại bản **chờ duyệt** của mình (xóa). Không phải của mình -> 404 · đã duyệt / bị từ
    chối -> 409 E-REC-4."""
    me = _me(member)
    return await idem.run(
        session, f"customer:{me.user_id}", lambda: manual.withdraw(session, me, record_id), 204
    )
