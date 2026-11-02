"""Bảng xếp hạng tốc độ cú đập của khu hội viên (T-030 giai đoạn A) – chỉ đọc."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from app.core.config import settings
from app.core.db import SessionDep
from app.modules.auth import api as auth
from app.modules.records import service
from app.modules.records.schemas import Period, SpeedRanking

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
