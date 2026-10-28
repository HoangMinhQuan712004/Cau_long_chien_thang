"""Dữ liệu ban đầu (Admin, 4 sân, bảng giá); chạy lại an toàn: python -m app.scripts.seed"""

import asyncio
from datetime import time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import Role, User
from app.modules.auth.utils import normalize_phone, password_problems
from app.modules.courts.models import Court, PriceRule

WEEKDAYS = [0, 1, 2, 3, 4]
WEEKEND = [5, 6]


# Mật khẩu mẫu trong config/.env.example – chỉ chấp nhận ở dev
_SAMPLE_PASSWORDS = {"admin12345", "Admin@12345"}


def _handover_password(name: str, value: str) -> str:
    """Mật khẩu bàn giao; production từ chối rỗng / mẫu / yếu để không lộ tài khoản quản trị."""
    if settings.is_production and (
        value in _SAMPLE_PASSWORDS
        or password_problems(value)
        or not any(c.isdigit() for c in value)
    ):
        raise ValueError(
            f"{name}: đặt mật khẩu bàn giao riêng (≥ 8 ký tự, có chữ in hoa và chữ số, khác mật "
            "khẩu mẫu)"
        )
    return value


async def _seed_accounts(session: AsyncSession) -> None:
    """Một Admin (SĐT, BR-001); tài khoản nhân viên do Admin tự cấp trong khu quản trị."""
    phone = normalize_phone(settings.FIRST_ADMIN_PHONE)
    if phone is None:
        raise ValueError("FIRST_ADMIN_PHONE không phải SĐT hợp lệ")
    admin = await session.scalar(select(User).where(User.role == Role.ADMIN).limit(1))
    if admin is None:
        session.add(
            User(
                phone=phone,
                full_name="Chủ sân",
                hashed_password=hash_password(
                    _handover_password("FIRST_ADMIN_PASSWORD", settings.FIRST_ADMIN_PASSWORD)
                ),
                role=Role.ADMIN,
            )
        )
        print(f"Created admin {phone}")
    elif admin.phone is None or admin.username is not None:
        # Admin bản cũ (đăng nhập email) ⇒ chuyển sang SĐT
        admin.phone = admin.phone or phone
        admin.username = None
        print(f"Updated admin login: phone {admin.phone}")


async def main() -> None:
    async with SessionLocal() as session:
        await _seed_accounts(session)

        if not await session.scalar(select(func.count()).select_from(Court)):
            session.add_all(
                Court(name=f"Sân {i}", slug=f"san-{i}", surface="Thảm PVC", sort_order=i)
                for i in range(1, 5)
            )
            print("Created 4 courts")

        if not await session.scalar(select(func.count()).select_from(PriceRule)):
            session.add_all(
                [
                    PriceRule(
                        name="Ngày thường - giờ thấp điểm",
                        days_of_week=WEEKDAYS,
                        start_time=time(5, 0),
                        end_time=time(17, 0),
                        price_per_hour=60_000,
                    ),
                    PriceRule(
                        name="Ngày thường - giờ vàng",
                        days_of_week=WEEKDAYS,
                        start_time=time(17, 0),
                        end_time=time(23, 0),
                        price_per_hour=100_000,
                    ),
                    PriceRule(
                        name="Cuối tuần",
                        days_of_week=WEEKEND,
                        start_time=time(5, 0),
                        end_time=time(23, 0),
                        price_per_hour=110_000,
                    ),
                ]
            )
            print("Created default price rules")

        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
