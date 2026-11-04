"""Tài khoản đăng nhập mẫu cho link dev (T-034) – chỉ ``app.scripts.seed_demo`` gọi (qua ``api``).

Dấu mẫu: tên **đúng** "Mẫu · Hội viên NN" **và** SĐT trong dải ``09990000xx`` – riêng "Mẫu · Hội
viên 01" được dùng SĐT người dùng chọn (``DEMO_MEMBER_PHONE``). Mật khẩu không bao giờ in / log;
tài khoản mẫu không bị bắt đổi mật khẩu (người dùng vào xem ngay).
"""

import secrets
from datetime import UTC, datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.modules.auth.models import Role, User

DEMO_PHONE_PREFIX = "09990000"
MAX_N = 99


def _name(n: int) -> str:
    return f"Mẫu · Hội viên {n:02d}"


def _is_demo():
    names = [_name(n) for n in range(1, MAX_N + 1)]
    return User.full_name.in_(names) & or_(
        User.phone.like(f"{DEMO_PHONE_PREFIX}%"), User.full_name == _name(1)
    )


async def foreign_demo_phones(session: AsyncSession, extra_phone: str | None = None) -> list[str]:
    """SĐT trong dải mẫu (và ``extra_phone``) đang thuộc tài khoản không có dấu mẫu -> dừng."""
    phones = User.phone.like(f"{DEMO_PHONE_PREFIX}%")
    if extra_phone:
        phones = phones | (User.phone == extra_phone)
    rows = await session.scalars(select(User.phone).where(phones, ~_is_demo()))
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
    """Xóa tài khoản mẫu (đủ dấu; phiên / OTP xóa theo FK cascade). Không commit."""
    result = await session.execute(delete(User).where(_is_demo()))
    return result.rowcount or 0
