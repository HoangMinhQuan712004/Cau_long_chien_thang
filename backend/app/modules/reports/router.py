"""Báo cáo & phân tích – chỉ Admin; NV gọi thẳng ⇒ 403 (SRS Báo cáo BR-001)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.db import SessionDep
from app.core.permissions import Perm, Principal, require
from app.modules.reports import service
from app.modules.reports.schemas import ReportOverviewOut

router = APIRouter(prefix="/admin/reports", tags=["admin: reports"])

ReportViewer = Annotated[Principal, Depends(require(Perm.REPORTS_VIEW))]


@router.get("/overview", response_model=ReportOverviewOut)
async def get_overview(
    _: ReportViewer,
    session: SessionDep,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
):
    """Cả màn trong một lần đọc: kỳ + kỳ trước, 3 chỉ số, doanh thu theo ngày / sân, heatmap.

    Thiếu cả hai ngày ⇒ Tuần (hôm nay − 6 → hôm nay). Doanh thu theo ngày chơi.
    Lỗi 422: E-REPORT-1 (Từ ngày sau Đến ngày), E-REPORT-2 (> 90 ngày), E-REPORT-3 (sau hôm nay).
    """
    return await service.overview(session, date_from, date_to)
