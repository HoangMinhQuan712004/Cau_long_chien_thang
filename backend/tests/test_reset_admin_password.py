"""T-013 AC31: lệnh ``python -m app.scripts.reset_admin_password``.

Admin phụ tạo bằng ``extra_admin`` (xóa khi xong) – không đụng mật khẩu Admin chính.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth.models import User
from app.scripts import reset_admin_password as cli
from tests.conftest import API, _client, extra_admin, sign_in

OLD = "Admin@12345"
NEW = "CuuAdmin2026!"


def answers(*values: str):
    it = iter(values)
    return lambda _prompt: next(it)


async def lock(user_id: int) -> None:
    async with SessionLocal() as s:
        await s.execute(
            update(User)
            .where(User.id == user_id)
            .values(failed_login_count=5, locked_until=datetime.now(UTC) + timedelta(minutes=9))
        )
        await s.commit()


async def test_cli_resets_admin_password(capsys):
    async with extra_admin(OLD) as (user_id, phone):
        async with _client() as c:
            assert (await sign_in(c, phone, OLD)).status_code == 200
            await lock(user_id)
            # Hai Admin -> lệnh hỏi SĐT (nhập kiểu +84 vẫn nhận)
            await cli.run(ask=answers(f"+84 {phone[1:]}"), secret=answers(NEW, NEW))

            r = await c.get(f"{API}/admin/auth/me")
            assert r.status_code == 401 and r.json()["detail"]["reason"] == "password_changed"
        out = capsys.readouterr()
        assert NEW not in out.out + out.err and phone not in out.out
        assert "Đã đăng xuất 1 phiên" in out.out

        async with _client() as c:
            assert (await sign_in(c, phone, OLD)).status_code == 401
            assert (await sign_in(c, phone, NEW)).status_code == 200  # khóa đã gỡ
        async with SessionLocal() as s:
            row = await s.scalar(
                select(AuditLog).where(
                    AuditLog.action == "auth.password_reset_cli",
                    AuditLog.entity_code == str(user_id),
                )
            )
            assert row is not None and row.actor_type == "system"
            assert NEW not in str(row.detail)
            assert (await s.get(User, user_id)).token_version == 1


@pytest.mark.parametrize(
    ("phone_answer", "passwords", "message"),
    [
        (None, ("CuuAdmin2026!", "Khac2026!"), "không khớp"),
        (None, ("yeu", "yeu"), "8 ký tự"),
        ("0999999999", ("CuuAdmin2026!", "CuuAdmin2026!"), "Không có Admin"),
    ],
)
async def test_cli_rejects_bad_input(phone_answer, passwords, message):
    async with extra_admin(OLD) as (user_id, phone):
        with pytest.raises(cli.ResetError, match=message):
            await cli.run(ask=answers(phone_answer or phone), secret=answers(*passwords))
        async with SessionLocal() as s:
            assert (await s.get(User, user_id)).token_version == 0


def test_cli_single_admin_is_not_asked():
    calls = []

    class _Admin:
        id, phone = 1, settings.FIRST_ADMIN_PHONE

    def ask(prompt):
        calls.append(prompt)
        return ""

    assert cli._choose_admin([_Admin()], ask).id == 1
    assert calls == []
    with pytest.raises(cli.ResetError):
        cli._choose_admin([], ask)
