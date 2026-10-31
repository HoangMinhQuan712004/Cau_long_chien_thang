"""Tài khoản web ↔ hồ sơ hội viên (T-016, ADR-009 sửa đổi 30/10 – mô hình của dev / PR #21).

Không lưu liên kết: hồ sơ của tài khoản = hồ sơ ``kind=member`` **cùng SĐT** (SĐT hồ sơ không đổi
được, ``users.phone`` và ``customer.phone`` đều unique), với điều kiện tài khoản được xem thẻ hội
viên (``member_accounts.can_view_member_card``: sân tạo tài khoản, hoặc SĐT đã xác minh OTP).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.auth import member_accounts
from app.modules.auth.models import Role, User


async def member_profile_id(session: AsyncSession, user: User) -> int | None:
    """Id hồ sơ hội viên của tài khoản khách này, hoặc None (chưa là hội viên / chưa xác minh)."""
    if user.role != Role.MEMBER or not user.phone or not member_accounts.can_view_member_card(user):
        return None
    # Import trong hàm: members -> booking_engine -> core.permissions -> auth (tránh vòng import)
    from app.modules.members import api as members

    return await members.member_id_by_phone(session, user.phone)
