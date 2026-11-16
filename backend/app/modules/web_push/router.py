"""Thông báo đẩy (T-076): cấu hình công khai + đăng ký thiết bị của tài khoản đang đăng nhập.

Không bắt ``Idempotency-Key`` (Q5): đăng ký là upsert theo endpoint, xóa idempotent, gửi thử có
giới hạn lượt. Hội viên (JWT) hoặc Admin / NV (phiên quản trị) đều dùng được.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from app.core import queue
from app.core.config import settings
from app.core.db import SessionDep
from app.core.middleware import require_origin
from app.core.permissions import OptionalPrincipal, Principal
from app.core.ratelimit import rate_limit
from app.modules.auth.deps import AuthStateDep, unauthenticated
from app.modules.web_push import service
from app.modules.web_push.schemas import (
    PushConfig,
    SubscriptionIn,
    SubscriptionOut,
    TestPushOut,
    UnsubscribeIn,
)

router = APIRouter(prefix="/push", tags=["push"])

TEST_LIMIT, TEST_WINDOW_S = 5, 600  # gửi thử: 5 lần / 10 phút / tài khoản


async def _signed_in(principal: OptionalPrincipal, state: AuthStateDep) -> Principal:
    if principal is None:
        raise unauthenticated(state.reason)
    return principal


SignedIn = Annotated[Principal, Depends(_signed_in)]


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


@router.get("/config", response_model=PushConfig)
async def push_config():
    """Công khai. ``enabled = false`` khi chưa cấu hình VAPID -> không hiện nút bật."""
    if not settings.push_enabled:
        return PushConfig(enabled=False, public_key=None)
    return PushConfig(enabled=True, public_key=settings.VAPID_PUBLIC_KEY)


@router.post(
    "/subscriptions",
    response_model=SubscriptionOut,
    status_code=status.HTTP_201_CREATED,
    responses={200: {"model": SubscriptionOut, "description": "Endpoint đã có (chuyển tài khoản)"}},
    dependencies=[Depends(require_origin), Depends(_no_store)],
)
async def subscribe(data: SubscriptionIn, me: SignedIn, session: SessionDep, response: Response):
    """Bật thông báo trên máy này. 201 mới · 200 endpoint đã có (chuyển sang tài khoản đang đăng
    nhập). 401 · 422 E-PUSH-1 (không phải https / host ngoài danh sách dịch vụ push) · 503
    E-PUSH-2 (chưa cấu hình VAPID)."""
    sub_id, created = await service.subscribe(session, me.actor_id, data)
    await session.commit()
    if not created:
        response.status_code = status.HTTP_200_OK
    return SubscriptionOut(id=sub_id)


@router.delete(
    "/subscriptions",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_origin)],
)
async def unsubscribe(data: UnsubscribeIn, me: SignedIn, session: SessionDep) -> None:
    """Tắt / đăng xuất: 204 kể cả khi không có hoặc là thiết bị của tài khoản khác (không xóa)."""
    await service.unsubscribe(session, me.actor_id, data.endpoint)
    await session.commit()


@router.post(
    "/test",
    response_model=TestPushOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[
        Depends(require_origin),
        Depends(rate_limit("push.test", TEST_LIMIT, TEST_WINDOW_S, key="user")),
    ],
)
async def send_test(me: SignedIn, session: SessionDep):
    """Gửi "Thông báo đã được bật trên thiết bị này" tới các thiết bị của **chính** tài khoản
    (job worker). 401 · 503 E-PUSH-2 · 429 E-SEC-5 (quá 5 lần / 10 phút)."""
    service.require_enabled()
    devices = await service.device_count(session, me.actor_id)
    if devices:
        url = "/hoi-vien" if me.actor_type == "customer" else "/admin"
        await queue.enqueue("push_test", me.actor_id, url)
    return TestPushOut(devices=devices)
