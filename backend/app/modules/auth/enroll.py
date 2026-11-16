"""R1 phía tài khoản (T-021): SĐT của tài khoản khách vừa xác minh OTP -> là hội viên.

Gọi sau khi ``phone_verified_at`` đã ghi, trong cùng transaction với việc xác minh (đăng ký,
``/auth/phone/verify``, OTP khi đặt online, Quên mật khẩu). Không commit.
"""

from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor
from app.core.errors import AppError
from app.modules.auth.models import Role, User

if TYPE_CHECKING:
    from app.modules.members.api import MemberEnsured


def account_locked() -> AppError:
    """Hồ sơ hội viên cùng SĐT đang Ngừng -> tài khoản bị khóa (quyết định 31/10)."""
    return AppError(
        "E-AUTH-31",
        "Tài khoản hội viên đang tạm ngừng. Vui lòng liên hệ quầy.",
        403,
    )


def actor_of(user: User) -> AuditActor:
    return AuditActor(type="customer", id=user.id, label=user.full_name)


async def enroll(session: AsyncSession, user: User) -> "MemberEnsured | None":
    """Bảo đảm hồ sơ hội viên cho tài khoản (R1); trả ``MemberEnsured`` hoặc None khi tài khoản
    không thuộc diện (không phải khách / chưa có SĐT đã xác minh).

    Hồ sơ đang Ngừng -> vẫn liên kết, tài khoản bị khóa (``is_active = False``, đăng xuất mọi JWT).
    """
    if user.role != Role.MEMBER or not user.phone or user.phone_verified_at is None:
        return None
    # Import trong hàm: members -> booking_engine -> core.permissions -> auth (tránh vòng import)
    from app.modules.members import api as members

    ensured = await members.ensure_member_for_phone(
        session, user.phone, user.full_name, actor_of(user)
    )
    if not ensured.is_active and user.is_active:
        user.is_active = False
        user.token_version += 1
    return ensured
