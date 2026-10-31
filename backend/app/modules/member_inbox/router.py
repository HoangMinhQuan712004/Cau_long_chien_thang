"""Thông báo của hội viên đang đăng nhập (T-017 AC22) – theo phiên, không theo id người trên URL."""

from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status

from app.core.db import SessionDep
from app.core.middleware import require_origin
from app.modules.auth import api as auth
from app.modules.member_inbox import service
from app.modules.member_inbox.schemas import NotificationList

router = APIRouter(prefix="/member-area/notifications", tags=["member-area"])


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("", response_model=NotificationList, dependencies=[Depends(no_store)])
async def list_notifications(
    member: auth.CurrentMember,
    session: SessionDep,
    unread: Annotated[bool | None, Query(description="true: chỉ chưa đọc")] = None,
):
    """Thông báo 30 ngày gần nhất (tối đa 50, mới nhất trước) + số chưa đọc. 403 E-HV-8."""
    return await service.list_for(session, member.customer_id, unread)


@router.post(
    "/read-all", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_origin)]
)
async def read_all(member: auth.CurrentMember, session: SessionDep) -> None:
    """Đã đọc hết (gửi lại vô hại – không cần Idempotency-Key)."""
    await service.mark_all_read(session, member.customer_id)
    await session.commit()


@router.post(
    "/{notification_id}/read",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_origin)],
)
async def read_one(
    notification_id: Annotated[int, Path(ge=1)], member: auth.CurrentMember, session: SessionDep
) -> None:
    """Đánh dấu đã đọc. Thông báo không phải của mình -> 404 E-NOT-FOUND (SEC6)."""
    await service.mark_read(session, member.customer_id, notification_id)
    await session.commit()
