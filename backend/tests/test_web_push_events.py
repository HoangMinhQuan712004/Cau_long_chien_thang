"""T-076 đợt 2: push theo sự kiện – hội viên (đổi sân, hủy, thanh toán, nhắc giờ, phòng chơi) và
nhân viên theo quyền (đặt online mới, tiền QR, tiền về cần xử lý). Dịch vụ push giả (conftest)."""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import delete, select, update

from app.core import events
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.auth import api as auth_api
from app.modules.auth.models import RolePermission, User
from app.modules.booking_engine import api as engine_api
from app.modules.booking_engine.api import publish_outbox
from app.modules.booking_engine.models import Booking, OutboxEvent
from app.modules.member_area import handlers as member_area
from app.modules.member_inbox.models import MemberNotification
from app.modules.web_push import messages
from tests import test_play_rooms as base
from tests.conftest import ENQUEUED_JOBS, PUSH, idem
from tests.conftest import push_testing as testing
from tests.helpers_booking import BK, member, new_court, temp
from tests.helpers_web import checkout, simulate, tomorrow
from tests.test_recurring import FD, body
from tests.test_recurring_list import LIST

people = base.people
PUSH_API = "/api/v1/push"


def fcm() -> str:
    return f"https://fcm.googleapis.com/fcm/send/{uuid.uuid4().hex}"


async def device(client) -> str:
    endpoint = fcm()
    r = await client.post(
        f"{PUSH_API}/subscriptions",
        json={"endpoint": endpoint, "keys": {"p256dh": "k" * 80, "auth": "a" * 16}},
    )
    assert r.status_code == 201, r.text
    return endpoint


async def flush() -> None:
    """Worker giả: phát outbox (handler chạy) rồi chạy các job push đã xếp."""
    while await publish_outbox(SessionLocal):
        pass
    await testing.drain(ENQUEUED_JOBS)


def to(endpoint: str) -> list[testing.Sent]:
    return [s for s in PUSH.sent if s.endpoint == endpoint]


async def inbox_texts(customer_id: int, kind: str) -> list[str]:
    async with SessionLocal() as s:
        rows = await s.scalars(
            select(MemberNotification)
            .where(MemberNotification.customer_id == customer_id, MemberNotification.kind == kind)
            .order_by(MemberNotification.id)
        )
        return [r.payload["text"] for r in rows]


async def member_order(admin, customer: dict, hour: int, days: int = 1) -> dict:
    """Đơn định kỳ (đặt trước được, khác đặt quầy chỉ hôm nay): ``days`` buổi liên tiếp từ ngày
    mai, mỗi buổi ``hour``–``hour + 1``."""
    court = await new_court(admin)
    start = tomorrow()
    data = body(court, start, start + timedelta(days=days - 1), hours=(hour, hour + 1))
    r = await admin.post(LIST, json={**data, "customer": customer}, headers=idem())
    assert r.status_code == 201, r.text
    return {**r.json(), "court": court}


async def member_block(staff, admin, hv, hour: int = 10) -> dict:
    order = await member_order(admin, member(hv.code), hour)
    first = sorted(order["bookings"], key=lambda b: b["code"])[0]
    return {**first, "order_code": order["order_code"], "court": order["court"]}


# ------------------------------------------------------------------ đổi sân (AC12)


async def test_moved_twice_two_pushes_redelivery_once(admin, staff, people):
    hv = await people("Hội Viên Đổi Sân")
    ep = await device(hv.client)
    b = await member_block(staff, admin, hv, hour=10)
    other = await new_court(admin)
    await flush()
    PUSH.clear()

    r = await admin.post(
        f"{BK}/items/{b['code']}/move",
        json={"resource_code": other["code"], "reason": "Ngừng sân", "version": b["version"]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    await flush()
    [sent] = to(ep)
    assert sent.title == "Buổi chơi đã được đổi" and sent.url == messages.MEMBER_HISTORY
    assert sent.body == (
        f"{b['order_code']} : {b['court']['name']} 10h–11h {tomorrow():%d/%m} → "
        f"{other['name']} 10h–11h {tomorrow():%d/%m}"
    )
    assert await inbox_texts(hv.customer_id, "booking.moved") == [sent.body]

    # Outbox giao lại cùng event (cùng event_id) -> không thêm thông báo
    async with SessionLocal() as s:
        row = await s.scalar(
            select(OutboxEvent)
            .where(OutboxEvent.event_type == "booking.moved")
            .order_by(OutboxEvent.id.desc())
            .limit(1)
        )
    await events.publish("booking.moved", {"tenant_id": 1, **row.payload, "event_id": row.id})
    await flush()
    assert len(to(ep)) == 1

    third = await new_court(admin)
    r = await admin.post(
        f"{BK}/items/{b['code']}/move",
        json={
            "resource_code": third["code"],
            "reason": "Ngừng sân",
            "version": r.json()["version"],
        },
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    await flush()
    assert len(to(ep)) == 2 and len(await inbox_texts(hv.customer_id, "booking.moved")) == 2


# ------------------------------------------------------------------ thanh toán (AC14, AC18)


async def test_order_collect_one_push_with_total_cash_not_to_staff(admin, staff, people):
    hv = await people("Hội Viên Thu Tiền")
    mine, admin_ep = await device(hv.client), await device(admin)
    order = await member_order(admin, member(hv.code), 8, days=2)
    await flush()
    PUSH.clear()
    r = await staff.post(
        f"{BK}/orders/{order['order_code']}/collect", json={"method": "cash"}, headers=idem()
    )
    assert r.status_code == 200, r.text
    await flush()
    [sent] = to(mine)
    total = sum(b["payment"]["amount"] for b in order["bookings"])
    assert sent.title == "Đã ghi nhận thanh toán"
    assert sent.body == f"{order['order_code']} · {total:,} đ · tiền mặt".replace(",", ".")
    assert not [s for s in to(admin_ep) if s.title == "Đã nhận tiền QR"]  # tiền mặt: không báo


async def test_counter_qr_paid_member_and_staff(admin, staff, people):
    hv = await people("Hội Viên QR")
    mine, admin_ep = await device(hv.client), await device(admin)
    order = await member_order(admin, member(hv.code), 13, days=2)
    total = sum(b["payment"]["amount"] for b in order["bookings"])
    await flush()
    PUSH.clear()
    assert await simulate(admin, order["order_code"].replace("-", ""), total) == "applied"
    await flush()
    [paid] = to(mine)
    assert paid.body.endswith("· chuyển khoản") and paid.body.startswith(order["order_code"])
    qr = [s for s in to(admin_ep) if s.title == "Đã nhận tiền QR"]
    assert len(qr) == 1
    assert qr[0].body == f"{order['order_code']} · {total:,} đ".replace(",", ".")
    assert qr[0].url == f"/admin/dat-san?date={tomorrow().isoformat()}"


async def test_online_paid_member_and_staff(admin, people):
    """AC14 + AC17: tiền online về -> hội viên "Đã ghi nhận thanh toán", nhân viên "Đặt online
    mới". Không tên / SĐT khách trên màn khóa."""
    hv = await people("Hội Viên Online")
    mine, admin_ep = await device(hv.client), await device(admin)
    court = await new_court(admin)
    # Hội viên đăng nhập (SĐT đã xác minh) tự đặt online
    r = await checkout(hv.client, [(court["code"], 15), (court["code"], 18)], phone=hv.phone)
    assert r.status_code == 201, r.text
    co = r.json()
    PUSH.clear()
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    await flush()
    [paid] = to(mine)
    assert paid.body == f"{co['order_code']} · {co['amount']:,} đ · chuyển khoản".replace(",", ".")
    [new] = [s for s in to(admin_ep) if s.title == "Đặt online mới"]
    assert new.body.startswith(f"{co['order_code']} · {court['name']} 15h–16h")
    assert "(+1 khung)" in new.body and hv.phone not in new.body
    assert new.url == f"/admin/dat-san?date={tomorrow().isoformat()}"


# ------------------------------------------------------------------ tiền về cần xử lý (AC19)


async def test_money_review_follows_permission(admin, staff):
    admin_ep, staff_ep = await device(admin), await device(staff)
    PUSH.clear()
    assert await simulate(admin, "BK99999999999", 123_000) == "unmatched"
    await flush()
    for ep in (admin_ep, staff_ep):
        [sent] = [s for s in to(ep) if s.title == "Tiền về cần xử lý"]
        assert sent.body == "123.000 đ · Không khớp mã" and sent.url == messages.MONEY_REVIEW_URL

    async with SessionLocal() as s:  # Admin gỡ quyền xem giao dịch của NV
        await s.execute(
            delete(RolePermission).where(
                RolePermission.role == "staff", RolePermission.perm == "booking.transactions.view"
            )
        )
        await s.commit()
    try:
        PUSH.clear()
        assert await simulate(admin, "BK99999999998", 50_000) == "unmatched"
        await flush()
        assert [s for s in to(admin_ep) if s.title == "Tiền về cần xử lý"]
        assert not to(staff_ep)
    finally:
        async with SessionLocal() as s:
            s.add(RolePermission(role="staff", perm="booking.transactions.view"))
            await s.commit()


# ------------------------------------------------------------------ nhắc giờ (AC8–AC11)


async def _backdate(code: str, created_at: datetime) -> None:
    async with SessionLocal() as s:
        await s.execute(update(Booking).where(Booking.code == code).values(created_at=created_at))
        await s.commit()


async def test_reminder_window_once_and_skips(admin, staff, people):
    hv = await people("Hội Viên Nhắc Giờ")
    ep = await device(hv.client)
    b = await member_block(staff, admin, hv, hour=18)
    late = await member_block(staff, admin, hv, hour=18)  # đặt sau mốc nhắc
    cancelled = await member_block(staff, admin, hv, hour=18)
    guest_code = (await member_order(admin, temp("Khách Không TK"), 18))["bookings"][0]["code"]
    async with SessionLocal() as s:
        start = await s.scalar(select(Booking.start_at).where(Booking.code == b["code"]))
    for code in (b["code"], cancelled["code"], guest_code):
        await _backdate(code, start - timedelta(hours=2))
    await _backdate(late["code"], start - timedelta(minutes=30))
    r = await admin.post(
        f"{FD}/items/{cancelled['code']}/cancel",
        json={"reason": "Sân bảo trì", "version": cancelled["version"]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    await flush()
    PUSH.clear()

    async def remind(minutes_before: int) -> list[str]:
        await member_area.send_reminders(start - timedelta(minutes=minutes_before))
        await testing.drain(ENQUEUED_JOBS)
        return [s.body for s in to(ep)]

    assert await remind(61) == []  # chưa tới mốc 60'
    assert await remind(15) == []  # còn đúng 15': bỏ
    got = await remind(60)
    assert got == [f"{b['court']['name']} · 18h–19h hôm nay · {b['order_code']}"]
    assert to(ep)[0].title == "Sắp đến giờ chơi" and to(ep)[0].url == messages.MEMBER_HISTORY
    assert await remind(30) == got and await remind(16) == got  # cron chạy lại: không trùng
    assert await inbox_texts(hv.customer_id, "booking.reminder") == got  # AC11
    async with SessionLocal() as s:
        rows = await s.scalars(
            select(MemberNotification.payload["code"].astext).where(
                MemberNotification.kind == "booking.reminder"
            )
        )
        reminded = set(rows)
    assert late["code"] not in reminded and cancelled["code"] not in reminded
    assert guest_code not in reminded


def test_reminder_says_date_when_not_today():
    """Buổi 0h nhắc lúc 23h hôm trước: câu ghi ngày, không ghi "hôm nay"; vé: tên sự kiện."""
    start = datetime(2026, 11, 17, 0, 0, tzinfo=settings.tz)
    item = engine_api.DueReminder(
        "BK-20261117-001-V03",
        "ticket",
        "BK-20261117-001-V03",
        "Giao lưu tối",
        "phone:0900000000",
        start,
        start + timedelta(hours=2),
    )
    text = member_area.reminder_text(item, start - timedelta(minutes=60))
    assert text == "Giao lưu tối · 0h–2h 17/11 · BK-20261117-001-V03"
    later = member_area.reminder_text(item, start - timedelta(minutes=0, seconds=-1))
    assert later == "Giao lưu tối · 0h–2h hôm nay · BK-20261117-001-V03"


# ------------------------------------------------------------------ hủy (AC13), phòng (AC15)


async def test_cancel_pushes_inbox_text(admin, staff, people):
    hv = await people("Hội Viên Bị Hủy")
    ep = await device(hv.client)
    b = await member_block(staff, admin, hv, hour=9)
    await flush()
    PUSH.clear()
    r = await admin.post(
        f"{FD}/items/{b['code']}/cancel",
        json={"reason": "Sân bảo trì", "version": b["version"]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    await flush()
    [sent] = to(ep)
    assert sent.title == "Buổi chơi đã bị hủy"
    assert sent.body == (await inbox_texts(hv.customer_id, "booking.cancelled"))[0]
    assert "Sân bảo trì" not in sent.body


async def test_room_join_request_push_has_no_name(admin, staff, people):
    host, asker = await people("Chủ Phòng Tên Riêng"), await people("Người Xin Tên Riêng")
    host_ep, asker_ep = await device(host.client), await device(asker.client)
    info = await base.room_for(staff, admin, host.code)
    room = info["room"]
    ENQUEUED_JOBS.clear()
    PUSH.clear()
    r = await base.post(asker.client, f"/{room.id}/join-requests", {"version": room.version})
    assert r.status_code == 200, r.text
    await testing.drain(ENQUEUED_JOBS)
    [sent] = to(host_ep)
    assert sent.title == "Có người xin vào phòng"
    assert sent.body.startswith("Có người xin vào phòng của bạn (") and "Tên Riêng" not in sent.body
    assert sent.url == f"/hoi-vien/phong/{room.id}"
    [inbox] = await inbox_texts(host.customer_id, "room.join_requested")
    assert "Người Xin Tên Riêng" in inbox  # hộp thông báo giữ câu có tên

    d = await base.detail(host.client, room.id)
    [req] = d["join_requests"]
    r = await base.post(
        host.client, f"/{room.id}/join-requests/{req['id']}/approve", {"version": d["version"]}
    )
    assert r.status_code == 200, r.text
    await testing.drain(ENQUEUED_JOBS)
    [ok] = to(asker_ep)
    assert ok.title == "Yêu cầu vào phòng được duyệt"


async def test_kinds_outside_list_not_pushed():
    """AC15–AC16: kind ngoài danh sách (mời, giao Host, thành tích…) chỉ ở hộp thông báo."""
    assert "room.invited" not in messages.PUSH_KINDS
    assert "record.approved" not in messages.PUSH_KINDS
    ENQUEUED_JOBS.clear()
    await events.publish(
        "member.notification_created", {"id": 1, "customer_id": 1, "kind": "room.invited"}
    )
    assert ENQUEUED_JOBS == []


# ------------------------------------------------------------------ tài khoản khóa (AC20)


async def test_locked_account_gets_nothing(admin, staff, people):
    hv = await people("Hội Viên Bị Khóa")
    ep = await device(hv.client)
    b = await member_block(staff, admin, hv, hour=7)
    await flush()
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.phone == hv.phone).values(is_active=False))
        await s.commit()
    PUSH.clear()
    r = await admin.post(
        f"{FD}/items/{b['code']}/cancel",
        json={"reason": "Sân bảo trì", "version": b["version"]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    await flush()
    assert to(ep) == []
    async with SessionLocal() as s:
        staff_ids = await auth_api.staff_user_ids_with(s, "booking.collect")
        uid = await s.scalar(select(User.id).where(User.phone == hv.phone))
    assert uid not in staff_ids
