"""Đăng ký thiết bị + gửi push (T-076). Hàm đăng ký / xóa **không commit**; ``deliver`` commit
(chạy trong job worker, tách khỏi transaction nghiệp vụ – push lỗi không làm hỏng luồng chính).
"""

import asyncio
import logging
from datetime import UTC, datetime

from sqlalchemy import delete, func, literal_column, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import AppError
from app.modules.web_push import endpoints
from app.modules.web_push.models import PushSubscription
from app.modules.web_push.schemas import SubscriptionIn
from app.modules.web_push.sender import Message, Result, Target, get_sender

logger = logging.getLogger(__name__)

MAX_DEVICES = 10  # mỗi tài khoản; cái thứ 11 -> xóa cái lâu không dùng nhất
MAX_FAILURES = 5  # lỗi liên tiếp (không phải 404 / 410) -> xóa
TEST_TITLE = "Chiến Thắng"
TEST_BODY = "Thông báo đã được bật trên thiết bị này"


def disabled() -> AppError:
    return AppError("E-PUSH-2", "Hệ thống chưa bật thông báo.", 503)


def require_enabled() -> None:
    if not settings.push_enabled:
        raise disabled()


async def subscribe(session: AsyncSession, user_id: int, data: SubscriptionIn) -> tuple[int, bool]:
    """Upsert theo endpoint: (id, mới tạo?). Endpoint đã có -> chuyển sang ``user_id`` này (máy
    dùng chung, đăng nhập tài khoản khác). 503 E-PUSH-2 · 422 E-PUSH-1."""
    require_enabled()
    host = endpoints.check(data.endpoint)
    now = datetime.now(UTC)
    values = {
        "user_id": user_id,
        "p256dh": data.keys.p256dh,
        "auth": data.keys.auth,
        "device_label": data.device_label,
        "last_seen_at": now,
        "fail_count": 0,
    }
    stmt = insert(PushSubscription).values(endpoint=data.endpoint, created_at=now, **values)
    row = (
        await session.execute(
            stmt.on_conflict_do_update(index_elements=["endpoint"], set_=values).returning(
                PushSubscription.id, literal_column("xmax = 0")
            )
        )
    ).one()
    sub_id, created = int(row[0]), bool(row[1])
    # Giữ tối đa MAX_DEVICES thiết bị / tài khoản: bỏ các máy lâu không dùng nhất
    keep = (
        select(PushSubscription.id)
        .where(PushSubscription.user_id == user_id)
        .order_by(PushSubscription.last_seen_at.desc(), PushSubscription.id.desc())
        .limit(MAX_DEVICES)
    )
    await session.execute(
        delete(PushSubscription).where(
            PushSubscription.user_id == user_id,
            PushSubscription.id.not_in(keep.scalar_subquery()),
            PushSubscription.id != sub_id,
        )
    )
    logger.info("Push subscription %s for user %s (%s)", sub_id, user_id, host)
    return sub_id, created


async def unsubscribe(session: AsyncSession, user_id: int, endpoint: str) -> None:
    """Chỉ xóa thiết bị của chính tài khoản; không có / của người khác -> không làm gì."""
    await session.execute(
        delete(PushSubscription).where(
            PushSubscription.user_id == user_id, PushSubscription.endpoint == endpoint
        )
    )


async def device_count(session: AsyncSession, user_id: int) -> int:
    count = await session.scalar(select(func.count()).where(PushSubscription.user_id == user_id))
    return count or 0


def _target(s: PushSubscription) -> Target:
    return Target(s.id, s.user_id, s.endpoint, s.p256dh, s.auth)


async def deliver(session: AsyncSession, user_ids: set[int], message: Message) -> int:
    """Gửi tới mọi thiết bị của ``user_ids``; trả số lần gửi thành công. Commit kết quả:
    404 / 410 -> xóa dòng · lỗi khác (kể cả 3xx, timeout) -> ``fail_count`` + 1, đủ 5 -> xóa ·
    thành công -> ``fail_count = 0``. Không có VAPID -> không gửi."""
    if not user_ids or not settings.push_enabled:
        return 0
    subs = list(
        await session.scalars(
            select(PushSubscription)
            .where(PushSubscription.user_id.in_(sorted(user_ids)))
            .order_by(PushSubscription.id)
        )
    )
    if not subs:
        return 0
    sender = get_sender()
    targets = [_target(s) for s in subs]
    results = await asyncio.gather(
        *(sender.send(t, message) for t in targets), return_exceptions=True
    )
    sent = 0
    now = datetime.now(UTC)
    for t, res in zip(targets, results, strict=True):
        result = res if isinstance(res, Result) else Result(None, "error")
        host = endpoints.host_of(t.endpoint) or "?"
        if result.ok:
            sent += 1
            await session.execute(
                update(PushSubscription)
                .where(PushSubscription.id == t.subscription_id)
                .values(fail_count=0, last_success_at=now)
            )
        elif result.gone:
            logger.info("Push subscription %s gone (%s %s)", t.subscription_id, host, result.status)
            await session.execute(
                delete(PushSubscription).where(PushSubscription.id == t.subscription_id)
            )
        else:
            logger.warning(
                "Push to subscription %s failed (%s %s)",
                t.subscription_id,
                host,
                result.status or result.error,
            )
            await session.execute(
                update(PushSubscription)
                .where(PushSubscription.id == t.subscription_id)
                .values(fail_count=PushSubscription.fail_count + 1)
            )
            await session.execute(
                delete(PushSubscription).where(
                    PushSubscription.id == t.subscription_id,
                    PushSubscription.fail_count >= MAX_FAILURES,
                )
            )
    await session.commit()
    return sent


def test_message(url: str) -> Message:
    return Message(title=TEST_TITLE, body=TEST_BODY, url=url, tag="push.test", ttl=600)
