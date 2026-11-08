"""Tạo dữ liệu ban đầu: tài khoản chủ sân + cấu hình booking engine (T-005) + hội viên mẫu (T-006).

Chạy: python -m app.scripts.seed  (chạy lại nhiều lần an toàn)

Booking engine: tenant + loại sân luôn được tạo; 6 sân, bảng giá, Lễ/Tết 2026 (dữ liệu prototype)
chỉ tạo khi ENV != production và engine chưa có sân nào.
"""

import asyncio
from datetime import date

from sqlalchemy import func, select

import app.models  # noqa: F401
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.modules.auth.models import Role, User
from app.modules.auth.utils import normalize_phone, password_problems
from app.modules.booking_engine import api as booking_engine
from app.modules.booking_engine.dto import (
    Actor,
    PriceCellIn,
    PriceTableUpdate,
    ResourceCreate,
    ResourceUpdate,
    SpecialDayIn,
)
from app.modules.members import api as members

SEED_ACTOR = Actor(type="system", id=None, label="Seed")
PEAKS = [("05:00", "07:00"), ("17:00", "21:00")]
# (tên, loại, mở, đóng, cao điểm, hoạt động) – theo prototype
DEMO_RESOURCES = [
    ("Sân 1", "thuong", "05:00", "22:00", PEAKS, True),
    ("Sân 2", "thuong", "05:00", "22:00", PEAKS, True),
    ("Sân 3", "thuong", "05:00", "22:00", PEAKS, True),
    ("Sân 4", "thuong", "05:00", "22:00", PEAKS, True),
    ("Sân 5", "vip", "06:00", "22:00", [("06:00", "07:00"), ("17:00", "21:00")], True),
    ("Sân 6", "vip", "05:00", "22:00", PEAKS, False),
]
# VND/giờ: loại sân -> loại ngày -> (thấp điểm, cao điểm)
DEMO_PRICES = {
    "thuong": {
        "weekday": (150_000, 180_000),
        "weekend": (210_000, 240_000),
        "holiday": (225_000, 260_000),
    },
    "vip": {
        "weekday": (250_000, 300_000),
        "weekend": (350_000, 400_000),
        "holiday": (375_000, 420_000),
    },
}
DEMO_HOLIDAYS_2026 = [
    (date(2026, 1, 1), date(2026, 1, 1), "Tết Dương lịch"),
    (date(2026, 2, 16), date(2026, 2, 22), "Tết Nguyên đán"),
    (date(2026, 4, 26), date(2026, 4, 26), "Giỗ Tổ Hùng Vương"),
    (date(2026, 4, 30), date(2026, 5, 1), "Giải phóng miền Nam, Quốc tế Lao động"),
    (date(2026, 9, 1), date(2026, 9, 2), "Quốc khánh"),
]

# Hội viên + hồ sơ tạm mẫu (prototype) – chỉ dữ liệu thử ở dev
DEMO_MEMBERS = [
    ("HV0012", "Trần Minh Đức", "0912111222", "Khá", True),
    ("HV0031", "Phạm Văn Nam", "0934567019", "Bán chuyên", True),
    ("HV0045", "Hoàng Thị Mai", "0978220145", "Trung bình", True),
    ("HV0058", "Nguyễn Văn Tú", "0905334058", "Trung bình yếu", True),
    ("HV0087", "Phạm Thu Trang", "0987654087", "Trung bình +", True),
    ("HV0102", "Nguyễn Thị Hoa", "0966102102", None, True),
    ("HV0115", "Vũ Đức Anh", "0915115300", "Chuyên nghiệp", True),
    ("HV0120", "Bùi Thanh Hà", "0938120777", "Yếu", False),
    ("HV0133", "Lý Minh Khoa", "0977133456", "Trung bình -", True),
    ("HV0141", "Ngô Đức Huy", "0909141662", None, True),
]
DEMO_TEMPS = [
    ("Lê Thị Lan", "0967532821"),
    ("Đỗ Quang Huy", "0903456712"),
    ("Nguyễn Văn An", "0987001321"),
    ("Trần Quốc Bảo", "0916778031"),
]


async def seed_members(session) -> None:
    if settings.is_production:
        return
    for code, name, phone, tier, active in DEMO_MEMBERS:
        await members.upsert_member(session, code, name, phone, tier, active)
    for name, phone in DEMO_TEMPS:
        await members.upsert_temp(session, name, phone)


async def seed_booking_engine(session) -> None:
    await booking_engine.ensure_tenant(session, code="chien-thang", name="Sân cầu lông Chiến Thắng")
    await booking_engine.upsert_resource_type(session, "thuong", "Sân thường", 1)
    await booking_engine.upsert_resource_type(session, "vip", "Sân VIP", 2)
    if settings.is_production or await booking_engine.resource_names(session):
        return

    for name, rtype, open_time, close_time, peaks, active in DEMO_RESOURCES:
        created = await booking_engine.create_resource(
            session,
            SEED_ACTOR,
            ResourceCreate(
                name=name,
                resource_type_code=rtype,
                open_time=open_time,
                close_time=close_time,
                peak_bands=peaks,
            ),
        )
        if not active:
            await booking_engine.update_resource(
                session,
                SEED_ACTOR,
                created.code,
                ResourceUpdate(version=created.version, is_active=False),
            )

    table = await booking_engine.get_price_table(session)
    await booking_engine.update_price_table(
        session,
        SEED_ACTOR,
        PriceTableUpdate(
            version=table.version,
            prices=[
                PriceCellIn(
                    resource_type_code=rtype,
                    day_type=day_type,
                    band=band,
                    price_per_hour=price,
                )
                for rtype, by_day in DEMO_PRICES.items()
                for day_type, pair in by_day.items()
                for band, price in zip(("offpeak", "peak"), pair, strict=True)
            ],
        ),
    )
    for date_from, date_to, name in DEMO_HOLIDAYS_2026:
        await booking_engine.create_special_day(
            session, SEED_ACTOR, SpecialDayIn(date_from=date_from, date_to=date_to, name=name)
        )
    print("Created booking engine demo config (6 resources, prices, holidays 2026)")


SAMPLE_ADMIN_PASSWORDS = {"Admin@12345", "admin12345", "change-me"}


async def seed_admin(session) -> None:
    """Chưa có Admin -> tạo từ FIRST_ADMIN_PHONE / FIRST_ADMIN_PASSWORD (T-013 AC33).

    Đã có Admin -> không đụng (không ghi đè mật khẩu, SĐT). Production từ chối mật khẩu mẫu / yếu.
    """
    if await session.scalar(select(User.id).where(User.role == Role.ADMIN).limit(1)):
        return
    phone = normalize_phone(settings.FIRST_ADMIN_PHONE)
    if phone is None:
        raise SystemExit("FIRST_ADMIN_PHONE thiếu hoặc không phải SĐT di động Việt Nam 10 số.")
    if settings.first_admin_phone_is_sample:
        raise SystemExit("FIRST_ADMIN_PHONE chưa được đặt hoặc vẫn là SĐT mẫu – đặt SĐT thật.")
    password = settings.FIRST_ADMIN_PASSWORD
    if settings.is_production and (
        password in SAMPLE_ADMIN_PASSWORDS or password_problems(password)
    ):
        raise SystemExit(
            "FIRST_ADMIN_PASSWORD là mật khẩu mẫu hoặc chưa đủ mạnh – đặt mật khẩu riêng."
        )
    session.add(
        User(
            phone=phone,
            phone_verified_at=func.now(),
            full_name="Chủ sân",
            hashed_password=hash_password(password),
            role=Role.ADMIN,
            is_active=True,
        )
    )
    print("Created admin (FIRST_ADMIN_PHONE)")


async def main() -> None:
    async with SessionLocal() as session:
        await seed_admin(session)
        await seed_booking_engine(session)
        await seed_members(session)
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
