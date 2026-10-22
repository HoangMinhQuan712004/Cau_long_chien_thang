"""Tạo dữ liệu ban đầu: tài khoản chủ sân, 4 sân, bảng giá mặc định.

Chạy: python -m app.scripts.seed  (chạy lại nhiều lần an toàn)
"""

import asyncio
from datetime import time

from sqlalchemy import func, select

import app.models  # noqa: F401
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import Role, User
from app.modules.courts.models import Court, PriceRule

WEEKDAYS = [0, 1, 2, 3, 4]
WEEKEND = [5, 6]


async def main() -> None:
    async with SessionLocal() as session:
        email = settings.FIRST_ADMIN_EMAIL.lower()
        if not await session.scalar(select(User).where(User.email == email)):
            session.add(
                User(
                    email=email,
                    full_name="Chủ sân",
                    hashed_password=hash_password(settings.FIRST_ADMIN_PASSWORD),
                    role=Role.ADMIN,
                )
            )
            print(f"Created admin {email}")

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
