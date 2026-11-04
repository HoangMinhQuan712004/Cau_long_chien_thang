"""T-034: dữ liệu mẫu cho link dev – AC1–AC6."""

import ast
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth.models import User
from app.modules.booking_engine.models import Booking, BookingOrder, EventSession, Ticket
from app.modules.members.models import Customer
from app.modules.play_rooms.models import PlayMatch, PlayRoom
from app.modules.records.models import SpeedRecord
from app.scripts import seed_demo
from tests.conftest import API, _client, idem, sign_in
from tests.helpers_booking import random_phone

M = f"{API}/members"
MA = f"{API}/member-area"
PASSWORD = "MauDev#2026-xyz"
DEMO = Customer.phone.like("09990000%") & Customer.full_name.startswith("Mẫu · ")


async def count(stmt) -> int:
    async with SessionLocal() as s:
        return await s.scalar(stmt)


async def demo_members() -> int:
    return await count(select(func.count()).select_from(Customer).where(DEMO))


@pytest.fixture
async def clean():
    """Mỗi test bắt đầu / kết thúc không có dữ liệu mẫu."""
    assert await seed_demo.run(True, None) == 0
    yield
    assert await seed_demo.run(True, None) == 0


def test_refuses_production(monkeypatch, capsys):
    monkeypatch.setattr(settings, "ENV", "production")
    assert seed_demo.main([]) == seed_demo.EXIT_PRODUCTION
    assert seed_demo.main(["--clear"]) == seed_demo.EXIT_PRODUCTION
    assert "production" in capsys.readouterr().err


async def test_seed_twice_then_clear_keeps_real_data(admin, clean, capsys):
    real_phone = random_phone()
    r = await admin.post(
        M, json={"full_name": "Hội Viên Thật", "phone": real_phone}, headers=idem()
    )
    assert r.status_code == 201, r.text

    assert await seed_demo.run(False, PASSWORD) == 0
    out = capsys.readouterr().out
    assert PASSWORD not in out and "0999000001" not in out  # AC5: không in mật khẩu / SĐT đầy đủ
    assert "0999 xxx 001" in out
    assert await demo_members() == 12
    async with SessionLocal() as s:
        tiers = set(await s.scalars(select(Customer.tier).where(DEMO)))
        assert len(tiers - {None}) == 8 and None in tiers  # 8 bậc + chưa xếp hạng
        rooms = list(
            await s.scalars(
                select(PlayRoom).where(
                    PlayRoom.host_customer_id.in_(select(Customer.id).where(DEMO))
                )
            )
        )
        ranges = {(r.min_tier, r.max_tier) for r in rooms if r.status == "open"}
        assert {(None, None), ("Trung bình", "Khá"), ("Khá", None)} <= ranges
        closed = [r for r in rooms if r.status == "closed"]
        assert len(closed) >= 5
        finished = await s.scalar(
            select(func.count())
            .select_from(PlayMatch)
            .where(PlayMatch.room_id.in_([r.id for r in closed]), PlayMatch.status == "finished")
        )
        assert finished >= 3 * len(closed)
        events = list(
            await s.scalars(select(EventSession).where(EventSession.name.startswith("[Mẫu]")))
        )
        assert len(events) == 2 and all(e.ticket_price > 0 for e in events)
        assert (
            await s.scalar(
                select(func.count())
                .select_from(Ticket)
                .where(Ticket.session_id.in_([e.id for e in events]))
            )
            >= 7
        )
        assert (
            await s.scalar(
                select(func.count())
                .select_from(SpeedRecord)
                .where(SpeedRecord.source_ref.startswith("demo:"))
            )
            == 51  # 12 người × 4 + 3 lần phá kỷ lục cụm
        )
        orders = list(
            await s.scalars(
                select(BookingOrder).where(
                    BookingOrder.kind == "recurring",
                    BookingOrder.customer_phone.like("09990000%"),
                )
            )
        )
        assert len(orders) == 2  # một chưa thu, một đã thu
        statuses = []
        for o in orders:
            paid = await s.scalars(select(Booking.payment_status).where(Booking.order_id == o.id))
            statuses.append(set(paid))
        assert {frozenset(x) for x in statuses} == {frozenset({"unpaid"}), frozenset({"paid"})}

    # AC4: đăng nhập tài khoản mẫu 01, các màn có số liệu
    async with _client() as c:
        r = await sign_in(c, "0999000001", PASSWORD)
        assert r.status_code == 200, r.text
        me = (await c.get(f"{MA}/me")).json()
        assert me["record_kmh"] is not None and me["tier"] == "Khá"
        month = datetime.now(settings.tz) - timedelta(days=3)  # có buổi chơi 3 ngày trước
        history = await c.get(f"{MA}/play-history", params={"month": month.strftime("%Y-%m")})
        assert history.status_code == 200 and history.json()["summary"]["sessions"] >= 1
        ranking = (await c.get(f"{MA}/speed-ranking", params={"period": "year"})).json()
        assert ranking["total_members"] == 12 and ranking["me"] is not None
        payments = (await c.get(f"{MA}/payments", params={"month": month.strftime("%Y-%m")})).json()
        assert payments["summary"]["count"] >= 1
        # Tổng quan v2: có lịch sắp tới, phòng đang trống (có phòng giới hạn hạng), kỷ lục mới
        o = (await c.get(f"{MA}/overview")).json()
        assert o["upcoming"] and o["record_kmh"] is not None and me["racket"]
        assert len(o["open_rooms"]) >= 2 and any(r["tier_range"] for r in o["open_rooms"])
        assert len(o["recent_records"]) >= 3 and o["recent_records"][0]["is_current"]
        assert o["ranking"]["me"] is not None and len(o["ranking"]["top3"]) == 3

    # AC1: chạy lần hai không nhân đôi
    assert await seed_demo.run(False, PASSWORD) == 0
    assert await demo_members() == 12
    assert (
        await count(
            select(func.count())
            .select_from(EventSession)
            .where(EventSession.name.startswith("[Mẫu]"))
        )
        == 2
    )

    # AC3: --clear xóa hết dấu mẫu, dữ liệu thật còn nguyên
    assert await seed_demo.run(True, None) == 0
    assert await demo_members() == 0
    assert (
        await count(select(func.count()).select_from(User).where(User.phone.like("09990000%"))) == 0
    )
    assert (
        await count(
            select(func.count())
            .select_from(BookingOrder)
            .where(BookingOrder.customer_phone.like("09990000%"))
        )
        == 0
    )
    assert (
        await count(
            select(func.count())
            .select_from(SpeedRecord)
            .where(SpeedRecord.source_ref.startswith("demo:"))
        )
        == 0
    )
    assert (
        await count(select(func.count()).select_from(Customer).where(Customer.phone == real_phone))
        == 1
    )
    async with SessionLocal() as s:
        await s.execute(delete(Customer).where(Customer.phone == real_phone))
        await s.commit()


async def test_without_password_no_login_accounts(clean, capsys):
    assert await seed_demo.run(False, None) == 0
    assert "DEMO_MEMBER_PASSWORD" in capsys.readouterr().out
    phones = await count(
        select(func.count()).select_from(User).where(User.phone.in_(["0999000001", "0999000002"]))
    )
    assert phones == 0
    assert (
        await count(select(func.count()).select_from(User).where(User.phone.like("09990000%")))
        == 10
    )


async def test_stops_when_demo_range_has_a_real_profile(admin, clean, capsys):
    r = await admin.post(M, json={"full_name": "Khách Thật", "phone": "0999000077"}, headers=idem())
    assert r.status_code == 201, r.text
    try:
        assert await seed_demo.run(False, PASSWORD) == seed_demo.EXIT_FOREIGN
        assert "0999 xxx 077" in capsys.readouterr().err
        assert await demo_members() == 0
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(Customer).where(Customer.phone == "0999000077"))
            await s.execute(delete(User).where(User.phone == "0999000077"))
            await s.commit()


def test_script_only_calls_module_facades():
    """AC6: script chỉ import ``app.modules.<x>.api`` (không model / service của module nào)."""
    path = Path(seed_demo.__file__)
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("app.modules")
        ):
            assert node.module.count(".") == 2, node.module  # app.modules.<x>
            assert [a.name for a in node.names] == ["api"], (
                node.module,
                [a.name for a in node.names],
            )


async def test_custom_first_phone_videos_and_clear(admin, clean, capsys):
    """Bổ sung 04/11: DEMO_MEMBER_PHONE cho Hội viên 01 (chỉ in SĐT che), DEMO_VIDEO_URLS gắn vào
    các lần phá kỷ lục; --clear xóa cả hồ sơ 01 dùng SĐT riêng (không cần biến)."""
    phone = random_phone()
    clip = "https://cdn.example.com/demo-smash.mp4"
    assert await seed_demo.run(False, PASSWORD, phone, [clip]) == 0
    out = capsys.readouterr().out
    assert phone not in out and f"{phone[:4]} xxx {phone[-3:]}" in out
    async with SessionLocal() as s:
        first = await s.scalar(select(Customer).where(Customer.full_name == "Mẫu · Hội viên 01"))
        assert first.phone == phone and first.racket
        videos = await s.scalar(
            select(func.count())
            .select_from(SpeedRecord)
            .where(SpeedRecord.source_ref.startswith("demo:"), SpeedRecord.video_url == clip)
        )
    assert videos == 1
    async with _client() as c:
        assert (await sign_in(c, phone, PASSWORD)).status_code == 200

    assert await seed_demo.run(True, None) == 0  # không truyền SĐT riêng vẫn xóa đúng 01
    async with SessionLocal() as s:
        assert await s.scalar(select(Customer).where(Customer.phone == phone)) is None
        assert await s.scalar(select(User).where(User.phone == phone)) is None


async def test_custom_first_phone_owned_by_real_profile_stops(admin, clean, capsys):
    phone = random_phone()
    r = await admin.post(M, json={"full_name": "Chủ SĐT Thật", "phone": phone}, headers=idem())
    assert r.status_code == 201, r.text
    try:
        assert await seed_demo.run(False, PASSWORD, phone) == seed_demo.EXIT_FOREIGN
        err = capsys.readouterr().err
        assert phone not in err and f"{phone[:4]} xxx {phone[-3:]}" in err
        assert await demo_members() == 0
        async with SessionLocal() as s:
            real = await s.scalar(select(Customer).where(Customer.phone == phone))
        assert real.full_name == "Chủ SĐT Thật"  # không bị ghi đè
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(Customer).where(Customer.phone == phone))
            await s.execute(delete(User).where(User.phone == phone))
            await s.commit()


def test_bad_first_phone_and_video_env(monkeypatch, capsys):
    monkeypatch.setenv("DEMO_MEMBER_PHONE", "12345")
    assert seed_demo.main([]) == seed_demo.EXIT_BAD_PHONE
    assert "DEMO_MEMBER_PHONE" in capsys.readouterr().err
    monkeypatch.setenv(
        "DEMO_VIDEO_URLS", "https://a.vn/1.mp4, http://b.vn/2.mp4 https://c.vn/3.webm"
    )
    assert seed_demo.video_urls_from_env() == ["https://a.vn/1.mp4", "https://c.vn/3.webm"]
