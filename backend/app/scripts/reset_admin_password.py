"""Cứu tài khoản Admin khi quên mật khẩu mà không nhận được OTP (T-013 AC31).

Chạy trên server:
    docker compose -p <project> exec api python -m app.scripts.reset_admin_password

Hỏi mật khẩu mới hai lần bằng ``getpass`` (không hiện, không nhận qua tham số dòng lệnh); nhiều
Admin -> hỏi SĐT. Đặt mật khẩu, ``token_version += 1``, thu hồi mọi phiên, gỡ khóa, ghi nhật ký
``auth.password_reset_cli``. Không bao giờ in mật khẩu.
"""

import asyncio
import getpass
import sys
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401
from app.core.audit import AuditActor, audit
from app.core.db import SessionLocal
from app.core.privacy import mask_phone
from app.core.security import hash_password
from app.modules.auth import sessions
from app.modules.auth.models import Role, User
from app.modules.auth.utils import normalize_phone, password_problems, password_rule_message

CLI_ACTOR = AuditActor(type="system", id=None, label="Lệnh reset_admin_password")


class ResetError(Exception):
    """Lỗi hiển thị cho người chạy lệnh (tiếng Việt, không chứa mật khẩu)."""


async def admins(session: AsyncSession) -> list[User]:
    return list(
        await session.scalars(select(User).where(User.role == Role.ADMIN).order_by(User.id))
    )


async def reset_password(session: AsyncSession, user_id: int, password: str) -> int:
    """Đặt mật khẩu mới cho Admin ``user_id`` (commit); trả số phiên đã thu hồi."""
    if problems := password_problems(password):
        raise ResetError(password_rule_message(problems))
    user = await session.scalar(
        select(User).where(User.id == user_id, User.role == Role.ADMIN).with_for_update()
    )
    if user is None:
        raise ResetError("Không tìm thấy tài khoản Admin.")
    revoked = await sessions.replace_password(session, user, hash_password(password))
    audit(
        session,
        CLI_ACTOR,
        "auth.password_reset_cli",
        "user",
        str(user.id),
        {"revoked_sessions": revoked},
    )
    await session.commit()
    return revoked


def _choose_admin(candidates: list[User], ask: Callable[[str], str]) -> User:
    if not candidates:
        raise ResetError("Chưa có tài khoản Admin nào. Chạy python -m app.scripts.seed trước.")
    if len(candidates) == 1:
        return candidates[0]
    phone = normalize_phone(ask(f"Có {len(candidates)} tài khoản Admin. Nhập SĐT của Admin: "))
    for user in candidates:
        if phone is not None and user.phone == phone:
            return user
    raise ResetError("Không có Admin nào dùng số điện thoại này.")


def _ask_password(secret: Callable[[str], str]) -> str:
    password = secret("Mật khẩu mới: ")
    if problems := password_problems(password):
        raise ResetError(password_rule_message(problems))
    if secret("Nhập lại mật khẩu mới: ") != password:
        raise ResetError("Hai lần nhập mật khẩu không khớp.")
    return password


async def run(
    ask: Callable[[str], str] = input, secret: Callable[[str], str] = getpass.getpass
) -> None:
    async with SessionLocal() as session:
        user = _choose_admin(await admins(session), ask)
        user_id, label = user.id, mask_phone(user.phone) if user.phone else f"#{user.id}"
        password = _ask_password(secret)
        revoked = await reset_password(session, user_id, password)
    print(f"Đã đặt lại mật khẩu Admin {label}. Đã đăng xuất {revoked} phiên đang mở.")


def main() -> None:
    try:
        asyncio.run(run())
    except ResetError as e:
        print(f"Lỗi: {e}", file=sys.stderr)
        sys.exit(1)
    except (KeyboardInterrupt, EOFError):
        print("\nĐã hủy.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
