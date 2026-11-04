"""Bảng xếp hạng tốc độ cú đập của khu hội viên (T-030 giai đoạn A) – chỉ đọc."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.core.config import settings
from app.core.db import SessionDep
from app.modules.auth import api as auth
from app.modules.records import service
from app.modules.records.schemas import Period, RecordVideoList, SpeedRanking, VideoPeriod

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
