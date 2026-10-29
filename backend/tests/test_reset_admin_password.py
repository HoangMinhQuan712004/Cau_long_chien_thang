"""T-013 AC31: lệnh ``python -m app.scripts.reset_admin_password``."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import Role, User
from app.scripts import reset_admin_password as cli
from tests.conftest import API, _client, sign_in, unique_phone

OLD = "Admin@12345"
NEW = "CuuAdmin2026!"


async def second_admin() -> tuple[int, str]:
    phone = unique_phone()
    async with SessionLocal() as s:
        user = User(
            phone=phone,
            phone_verified_at=datetime.now(UTC),
            full_name="Admin dự phòng",
            hashed_password=hash_password(OLD),
            role=Role.ADMIN,
            failed_login_count=5,
            locked_until=datetime.now(UTC) + timedelta(minutes=10),
        )
        s.add(user)
        await s.commit()
        return user.id, phone


def answers(*values: str):
    it = iter(values)
    return lambda _prompt: next(it)


async def test_cli_resets_admin_password(capsys):
    user_id, phone = await second_admin()
    # Có phiên đang mở (gỡ khóa tạm để đăng nhập được)
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.id == user_id).values(locked_until=None))
        await s.commit()
    async with _client() as c:
        assert (await sign_in(c, phone, OLD)).status_code == 200
        async with SessionLocal() as s:
            await s.execute(
                update(User)
                .where(User.id == user_id)
                .values(failed_login_count=5, locked_until=datetime.now(UTC) + timedelta(minutes=9))
            )
            await s.commit()

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
                AuditLog.action == "auth.password_reset_cli", AuditLog.entity_code == str(user_id)
            )
        )
        assert row is not None and row.actor_type == "system"
        user = await s.get(User, user_id)
        assert user.token_version == 1


@pytest.mark.parametrize(
    ("phone_answer", "passwords", "message"),
    [
        (None, ("CuuAdmin2026!", "Khac2026!"), "không khớp"),
        (None, ("yeu", "yeu"), "8 ký tự"),
        ("0999999999", ("CuuAdmin2026!", "CuuAdmin2026!"), "Không có Admin"),
    ],
)
async def test_cli_rejects_bad_input(phone_answer, passwords, message):
    user_id, phone = await second_admin()
    with pytest.raises(cli.ResetError, match=message):
        await cli.run(ask=answers(phone_answer or phone), secret=answers(*passwords))
    async with SessionLocal() as s:
        assert (await s.get(User, user_id)).token_version == 0


async def test_cli_single_admin_is_not_asked(monkeypatch):
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
