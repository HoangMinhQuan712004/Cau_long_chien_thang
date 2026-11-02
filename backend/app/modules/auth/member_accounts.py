"""Tài khoản khách của hội viên (T-015): sân thêm hội viên -> có tài khoản đăng nhập theo SĐT.

Mật khẩu ban đầu = SĐT (người dùng chọn), ``must_change_password`` bắt đổi trước khi dùng. Ngoại lệ
"mật khẩu = SĐT" chỉ có ở đây; đổi / đặt lại sau đó theo quy tắc mật khẩu và khác SĐT.

Hạn 3 ngày (``MEMBER_INITIAL_PASSWORD_DAYS``, từ ``member_account_at``): quá hạn mà vẫn chưa đổi
-> đăng nhập đúng mật khẩu vẫn KHÔNG cấp phiên, phiên đã cấp cũng bị chặn (403 ``E-AUTH-30``); chỉ
còn Quên mật khẩu (OTP) – xong thì bỏ cờ. Sai mật khẩu vẫn là lỗi sai mật khẩu, có đếm lần sai.
Hàm ở đây **không commit** (cùng transaction với hồ sơ hội viên) trừ ``change_password``.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.config import settings
from app.core.errors import AppError
from app.core.security import hash_password, verify_password
from app.modules.auth import sessions
from app.modules.auth.models import Role, User


def must_change() -> AppError:
    return AppError("E-AUTH-25", "Vui lòng đổi mật khẩu trước khi tiếp tục.", 403)


def initial_password_expired(user: User, now: datetime | None = None) -> bool:
    """Còn mật khẩu ban đầu và đã quá ``MEMBER_INITIAL_PASSWORD_DAYS`` ngày kể từ lúc sân tạo."""
    if not user.must_change_password or user.member_account_at is None:
        return False
    return (now or datetime.now(UTC)) >= initial_password_deadline(user.member_account_at)


def expired_error() -> AppError:
    return AppError(
        "E-AUTH-30",
        "Mật khẩu ban đầu đã hết hạn. Vui lòng bấm Quên mật khẩu để đặt mật khẩu mới.",
        403,
    )


def same_as_phone() -> AppError:
    return AppError("E-AUTH-26", "Mật khẩu không được trùng số điện thoại.", 422)


def initial_password_deadline(created_at: datetime) -> datetime:
    """Hạn đổi mật khẩu ban đầu của tài khoản sân tạo lúc ``created_at``."""
    return created_at + timedelta(days=settings.MEMBER_INITIAL_PASSWORD_DAYS)


async def ensure_customer_account(
    session: AsyncSession, phone: str, full_name: str, active: bool
) -> bool:
    """Tạo tài khoản khách cho SĐT nếu chưa có; True nếu vừa tạo."""
    return await create_customer_account(session, phone, full_name, active) is not None


async def create_customer_account(
    session: AsyncSession, phone: str, full_name: str, active: bool
) -> datetime | None:
    """Tạo tài khoản khách cho SĐT nếu chưa có -> hạn đổi mật khẩu ban đầu; đã có -> None.

    Đã có tài khoản (khách tự đăng ký, hoặc Admin / NV) -> không đụng (không đổi mật khẩu).
    ``ON CONFLICT DO NOTHING``: hai request cùng SĐT -> một dòng, không lỗi.
    """
    if await session.scalar(select(User.id).where(User.phone == phone)):
        return None
    now = datetime.now(UTC)
    created = await session.scalar(
        insert(User)
        .values(
            phone=phone,
            full_name=full_name,
            hashed_password=hash_password(phone),
            role=Role.MEMBER,
            is_active=active,
            must_change_password=True,
            member_account_at=now,
        )
        .on_conflict_do_nothing(index_elements=[User.phone])
        .returning(User.id)
    )
    return initial_password_deadline(now) if created is not None else None


async def set_customer_account_active(session: AsyncSession, phone: str, active: bool) -> None:
    """Hội viên Ngừng -> khóa tài khoản **khách** cùng SĐT (tăng ``token_version`` = đăng xuất mọi
    JWT); Hoạt động lại -> mở. Tài khoản Admin / NV không đụng."""
    values: dict = {"is_active": active}
    if not active:
        values["token_version"] = User.token_version + 1
    await session.execute(
        update(User)
        .where(User.phone == phone, User.role == Role.MEMBER, User.is_active.is_(not active))
        .values(**values)
    )


def can_view_member_card(user: User) -> bool:
    """Tài khoản do luồng hội viên tạo, hoặc SĐT đã xác minh OTP – chặn trường hợp ai đó tự đăng
    ký trước bằng SĐT của hội viên (``/auth/register`` không OTP)."""
    return user.member_account_at is not None or user.phone_verified_at is not None


async def change_password(
    session: AsyncSession, user_id: int, current: str | None, new_password: str
) -> User:
    """Đổi mật khẩu của khách (commit): cờ ``must_change_password`` -> không cần mật khẩu cũ.

    Bỏ cờ, ``token_version += 1`` (JWT cũ hết hiệu lực – lớp gọi cấp cookie mới).
    """
    user = await session.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None or not user.is_active:
        raise AppError("E-AUTH-1", "Chưa đăng nhập", 401, reason="unauthenticated")
    if not user.must_change_password and not (
        current and user.hashed_password and verify_password(current, user.hashed_password)
    ):
        raise AppError("E-AUTH-28", "Mật khẩu hiện tại không đúng.", 400)
    if user.phone and new_password == user.phone:
        raise same_as_phone()
    await sessions.replace_password(session, user, hash_password(new_password))
    user.must_change_password = False
    audit(
        session,
        AuditActor(
            type=sessions.actor_type_of(user.role), id=user.id, label=sessions.actor_label(user)
        ),
        "auth.password_changed",
        "user",
        str(user.id),
    )
    await session.commit()
    await session.refresh(user)
    return user
