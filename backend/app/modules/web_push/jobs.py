"""Job ARQ gửi push (T-076) – chạy trong worker, mỗi job một session riêng, lỗi không lan ra."""

import logging

from app.core.db import SessionLocal
from app.modules.auth import api as auth
from app.modules.member_inbox import api as inbox
from app.modules.members import api as members
from app.modules.web_push import messages, service
from app.modules.web_push.sender import Message

logger = logging.getLogger(__name__)


async def push_test(ctx, user_id: int, url: str) -> int:
    """Gửi thử: chỉ các thiết bị của chính tài khoản (đang hoạt động)."""
    async with SessionLocal() as session:
        if not await auth.active_user_ids(session, {user_id}):
            return 0
        return await service.deliver(session, {user_id}, service.test_message(url))


async def push_member_notification(ctx, notification_id: int) -> int:
    """Thông báo hộp hội viên (kind trong ADR-015) -> các thiết bị của tài khoản hội viên đó.
    Người nhận tính lúc gửi: hội viên có tài khoản liên kết đang hoạt động (AC9, AC20)."""
    async with SessionLocal() as session:
        view = await inbox.push_view(session, notification_id)
        if view is None or view.kind not in messages.PUSH_KINDS:
            return 0
        person = (await members.room_people(session, {view.customer_id})).get(view.customer_id)
        if person is None or person.member_code is None or not person.phone:
            return 0
        user_id = await auth.member_user_id(session, person.phone)
        if user_id is None:
            return 0
        msg = messages.member_message(view.id, view.kind, view.text, view.link)
        return await service.deliver(session, {user_id}, msg)


async def push_staff(ctx, kind: str, perm: str, body: str, url: str, tag: str) -> int:
    """Thông báo nhân viên: Admin / NV đang hoạt động có quyền ``perm`` **lúc gửi** (AC19)."""
    async with SessionLocal() as session:
        user_ids = await auth.staff_user_ids_with(session, perm)
        msg = Message(title=messages.STAFF_TITLES[kind], body=body, url=url, tag=tag)
        return await service.deliver(session, user_ids, msg)
