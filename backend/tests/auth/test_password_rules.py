import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth.models import (
    Role,
    User,
)
from app.modules.auth.utils import (
    password_problems,
)
from tests.client import API
from tests.conftest import new_customer
from tests.helpers import (
    RESET_CONFIRM,
    STAFF,
    get_me,
    get_reset_token,
    new_phone,
    new_staff,
    request_otp,
    rewind_requests,
)

WEAK_PASSWORDS = [
    ("Ab@1234", "Mật khẩu cần ít nhất 8 ký tự."),
    ("matkhau@123", "Mật khẩu cần 1 chữ in hoa."),
    ("Matkhauab", "Mật khẩu cần 1 chữ số hoặc ký tự đặc biệt."),
    ("Mat Khau Ab", "Mật khẩu cần 1 chữ số hoặc ký tự đặc biệt."),  # khoảng trắng không tính
    ("ab", "Mật khẩu cần ít nhất 8 ký tự, 1 chữ in hoa và 1 chữ số hoặc ký tự đặc biệt."),
]


# Chữ in hoa có dấu cũng tính; chữ số hoặc ký tự không phải chữ/số/khoảng trắng đều được
GOOD_PASSWORDS = ["Matkhau12", "Matkhau!!", "đặtmậtkhẩuĐ#", "ĂnCơm~~~", "abcdefG_"]


async def _password_routes(admin: AsyncClient, anon: AsyncClient, sent: dict[int, str]):
    """(tên, hàm gửi mật khẩu ⇒ Response) cho cả 4 chỗ đặt mật khẩu mới."""
    staff = await new_staff(admin)

    async def register(password: str) -> Response:
        return await anon.post(
            f"{API}/auth/register",
            json={"full_name": "Khách", "phone": new_phone(), "password": password},
        )

    async def create_staff(password: str) -> Response:
        return await admin.post(STAFF, json={"full_name": "Nhân Viên", "password": password})

    async def reset_staff(password: str) -> Response:
        return await admin.post(f"{STAFF}/{staff['id']}/password", json={"password": password})

    async def reset_confirm(password: str) -> Response:
        async with new_customer() as c:
            user = await get_me(c)
        await rewind_requests(settings.OTP_RESEND_SECONDS)
        token = await get_reset_token(anon, user["phone"], await request_otp(anon, sent, user))
        return await anon.post(RESET_CONFIRM, json={"reset_token": token, "password": password})

    return [register, create_staff, reset_staff, reset_confirm]


async def test_new_password_rule_on_every_route(admin, anon, sent_otps):
    for route in await _password_routes(admin, anon, sent_otps):
        for password, message in WEAK_PASSWORDS:
            r = await route(password)
            assert r.status_code == 422, (route.__name__, password, r.text)
            [error] = [e for e in r.json()["detail"] if e["loc"][-1] == "password"]
            assert error["type"] == "weak_password"
            assert error["msg"] == message, route.__name__
        r = await route("a" * 120 + "A@" + "b" * 7)  # > 128
        assert r.status_code == 422
        for password in GOOD_PASSWORDS[:1] if route.__name__ == "reset_confirm" else GOOD_PASSWORDS:
            r = await route(password)
            assert r.status_code in (201, 204), (route.__name__, password, r.text)


def test_password_problems_rule():
    for password in GOOD_PASSWORDS:
        assert password_problems(password) == [], password
    assert password_problems("x" * 7) == [
        "ít nhất 8 ký tự",
        "1 chữ in hoa",
        "1 chữ số hoặc ký tự đặc biệt",
    ]


@pytest.mark.parametrize(
    "password",
    [
        "",
        "admin12345",
        "Admin@12345",  # mẫu trong .env.example
        "ngan1",
        "chicochu",
        "12345678",
        "BanGiaoMoi!",  # thiếu số (riêng mật khẩu bàn giao)
        "bangiao@2026",  # thiếu chữ in hoa
    ],
)
def test_seed_rejects_weak_handover_password_in_production(monkeypatch, password):
    from app.scripts import seed

    monkeypatch.setattr(settings, "ENV", "production")
    with pytest.raises(ValueError):
        seed._handover_password("FIRST_ADMIN_PASSWORD", password)
    assert seed._handover_password("FIRST_ADMIN_PASSWORD", "BanGiao@2026") == "BanGiao@2026"


async def test_seed_creates_only_admin():
    async with SessionLocal() as s:
        admins = (await s.scalars(select(User).where(User.role == Role.ADMIN))).all()
    assert len(admins) == 1
