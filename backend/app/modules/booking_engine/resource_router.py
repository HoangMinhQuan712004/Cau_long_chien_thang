"""Ngăn chi tiết sân (/admin/san): chi tiết + thống kê theo kỳ – router phụ gắn vào ``router``."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.db import SessionDep
from app.core.permissions import Perm, Principal, require
from app.modules.booking_engine import resource_detail
from app.modules.booking_engine.resource_detail import (
    Period,
    ResourceDetailOut,
    ResourceStatsOut,
)
from app.modules.booking_engine.tenant import current_tenant_id

router = APIRouter()
ConfigManager = Annotated[Principal, Depends(require(Perm.BOOKING_CONFIG_MANAGE))]


@router.get("/resources/{code}/detail", response_model=ResourceDetailOut)
async def resource_detail_view(code: str, _: ConfigManager, session: SessionDep):
    """Thông tin sân + giá của loại sân (chỉ xem) + tối đa 20 booking / sự kiện sắp tới."""
    return await resource_detail.resource_detail(session, current_tenant_id(), code)


@router.get("/resources/{code}/stats", response_model=ResourceStatsOut)
async def resource_stats(
    code: str,
    _: ConfigManager,
    session: SessionDep,
    period: Period = "month",
    day: Annotated[date | None, Query(alias="date")] = None,
):
    """Thống kê sân theo tuần / tháng / năm chứa ``date`` (mặc định hôm nay), tính tới hôm nay;
    kèm kỳ trước cùng số ngày. Cách tính như màn Báo cáo."""
    return await resource_detail.resource_stats(session, current_tenant_id(), code, period, day)
