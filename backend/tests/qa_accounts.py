# ruff: noqa: E501
"""Helper của QA (không phải test): tạo tài khoản khách **chưa xác minh SĐT** thẳng trong DB.

Từ T-021 ``POST /auth/register`` trả 410 (đăng ký không OTP đã đóng), nhưng nhiều test QA vẫn cần một tài khoản
đời T-013 (SĐT chưa xác minh, role ``member``, không do sân tạo). Đăng ký thật 2 bước dùng ``tests.conftest.register``.
"""

from httpx import AsyncClient

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import Role, User
from tests.conftest import API, CUSTOMER_PASSWORD


async def db_account(
    client: AsyncClient | None,
    phone: str,
    full_name: str = "Khách QA",
    password: str = CUSTOMER_PASSWORD,
) -> str:
    """Tạo tài khoản chưa xác minh; có ``client`` thì đăng nhập luôn trên client đó. Trả SĐT."""
    async with SessionLocal() as s:
        s.add(
            User(
                phone=phone,
                full_name=full_name,
                hashed_password=hash_password(password),
                role=Role.MEMBER,
                is_active=True,
            )
        )
        await s.commit()
    if client is not None:
        r = await client.post(f"{API}/auth/sign-in", json={"login": phone, "password": password})
        assert r.status_code == 200, r.text
    return phone
