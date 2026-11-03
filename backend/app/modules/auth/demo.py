"""Tài khoản đăng nhập mẫu cho link dev (T-034) – chỉ ``app.scripts.seed_demo`` gọi (qua ``api``).

Dấu mẫu: tên bắt đầu bằng "Mẫu · " **và** SĐT trong dải ``09990000xx``. Mật khẩu không bao giờ in /
log; tài khoản mẫu không bị bắt đổi mật khẩu (người dùng vào xem ngay).
"""

import secrets
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.modules.auth.models import Role, User

DEMO_NAME_PREFIX = "Mẫu · "
DEMO_PHONE_PREFIX = "09990000"


def _is_demo():
    return User.phone.like(f"{DEMO_PHONE_PREFIX}%") & User.full_name.startswith(DEMO_NAME_PREFIX)


async def foreign_demo_phones(session: AsyncSession) -> list[str]:
    """SĐT trong dải mẫu đang thuộc tài khoản không có dấu mẫu -> script dừng."""
    rows = await session.scalars(
        select(User.phone).where(
            User.phone.like(f"{DEMO_PHONE_PREFIX}%"), ~User.full_name.startswith(DEMO_NAME_PREFIX)
        )
    )
    return [p for p in rows if p]


async def create_account(
    session: AsyncSession, phone: str, full_name: str, password: str | None
) -> None:
    """Tài khoản khách đã xác minh SĐT (liên kết hội viên). ``password=None`` -> mật khẩu ngẫu nhiên
    không ai biết (không đăng nhập được, chỉ để hồ sơ là "hội viên có liên kết"). Không commit."""
    session.add(
        User(
            phone=phone,
            full_name=full_name,
            hashed_password=hash_password(password or secrets.token_urlsafe(32)),
            role=Role.MEMBER,
            is_active=True,
            must_change_password=False,
            phone_verified_at=datetime.now(UTC),
        )
    )
    await session.flush()


async def purge_demo(session: AsyncSession) -> int:
    """Xóa tài khoản mẫu (đủ hai dấu; phiên / OTP xóa theo FK cascade). Không commit."""
    result = await session.execute(delete(User).where(_is_demo()))
    return result.rowcount or 0
