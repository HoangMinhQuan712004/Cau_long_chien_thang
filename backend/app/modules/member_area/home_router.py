"""Tổng quan + Lịch sử thanh toán khu hội viên (T-018) – theo phiên, ``no-store``."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Query, Response

from app.core.db import SessionDep
from app.modules.auth import api as auth
from app.modules.member_area import home
from app.modules.member_area.home_schemas import Overview, PaymentItem, PaymentList

router = APIRouter(prefix="/member-area", tags=["member-area"])


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/overview", response_model=Overview, dependencies=[Depends(no_store)])
async def overview(member: auth.CurrentMember, session: SessionDep):
    """Trang Tổng quan (AC1–AC3): tên chào, lịch hôm nay, lịch sắp tới, số thông báo chưa đọc.
    403 E-HV-8 (chưa là hội viên)."""
    return await home.overview(session, member.customer_id)


@router.get("/payments", response_model=PaymentList, dependencies=[Depends(no_store)])
async def payments(
    member: auth.CurrentMember,
    session: SessionDep,
    month: Annotated[
        str | None, Query(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM, mặc định tháng này")
    ] = None,
    kind: Annotated[Literal["all", "booking", "ticket"], Query()] = "all",
):
    """Các khoản **đã thanh toán** (booking + vé) theo tháng thanh toán, giờ VN (AC7–AC10)."""
    return await home.payments(session, member.customer_id, month, kind)


@router.get("/payments/{code}", response_model=PaymentItem, dependencies=[Depends(no_store)])
async def payment(
    code: Annotated[str, Path(max_length=40, description="``code`` của dòng (id nội bộ)")],
    member: auth.CurrentMember,
    session: SessionDep,
):
    """Chi tiết một khoản đã thanh toán của mình; khác -> 404 E-NOT-FOUND."""
    return await home.payment(session, member.customer_id, code)
