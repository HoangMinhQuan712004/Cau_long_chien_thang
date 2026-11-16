# ruff: noqa: E501
"""QA T-076 (API, AC8–AC20, AC22–AC23): push theo sự kiện với dịch vụ push giả.

Góc nhìn độc lập với ``test_web_push_events.py`` của BACKEND: biên nhắc giờ đến từng giây (đúng 15 phút bỏ, hơn 15 phút một giây nhắc;
``created_at`` đúng mốc 60 phút nhắc, trễ một giây thì không), cron chạy song song vẫn một lần, hội viên chưa bật thiết bị vẫn có hộp,
đổi sân khối của khách không tài khoản / đổi lỗi không push, hai khối hai lần đổi hai push, hai lượt thu hai push với tổng tiền đúng,
nhân viên theo quyền tại lúc gửi (gỡ ``booking.calendar.view`` / ``booking.collect``), tài khoản khóa, đủ ba kết quả tiền về cần xử lý
và ``applied`` thì im lặng, push lỗi / sender ném lỗi không làm hỏng luồng chính, danh sách ``kind`` có push khớp đúng spec,
không rò họ tên / SĐT / endpoint trên màn khóa.
"""

import asyncio
from datetime import timedelta

from sqlalchemy import delete, select, update

from app.core import events
from app.core.db import SessionLocal
from app.modules.auth.models import RolePermission, User
from app.modules.booking_engine.models import Booking
from app.modules.member_area import handlers as member_area
from app.modules.member_inbox.models import MemberNotification
from app.modules.web_push import messages
from app.modules.web_push.models import PushSubscription
from tests import test_play_rooms as base
from tests.conftest import ENQUEUED_JOBS, PUSH, idem
from tests.conftest import push_testing as testing
from tests.helpers_booking import BK, member, new_court, temp
from tests.helpers_web import checkout, simulate
from tests.test_web_push_events import (
    _backdate,
    device,
    flush,
    inbox_texts,
    member_block,
    member_order,
    to,
)

people = base.people


def vnd(n: int) -> str:
    return f"{n:,}".replace(",", ".")


async def start_of(code: str):
    async with SessionLocal() as s:
        return await s.scalar(select(Booking.start_at).where(Booking.code == code))


async def user_of(endpoint: str) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(PushSubscription.user_id).where(PushSubscription.endpoint == endpoint)
        )


async def fail_count(endpoint: str) -> int | None:
    async with SessionLocal() as s:
        return await s.scalar(
            select(PushSubscription.fail_count).where(PushSubscription.endpoint == endpoint)
        )


def assert_no_identity(sent, *secrets):
    """AC22: không họ tên, SĐT (đầy đủ hay 6 số cuối) trên màn khóa."""
    for s in sent:
        text = f"{s.title} | {s.body} | {s.url} | {s.tag}"
        for secret in secrets:
            for part in {secret, secret[-6:]} if secret.isdigit() else {secret}:
                assert part not in text, f"{part!r} lộ trong push {s.title!r}"


async def drop_permission(role: str, perm: str) -> None:
    async with SessionLocal() as s:
        await s.execute(
            delete(RolePermission).where(RolePermission.role == role, RolePermission.perm == perm)
        )
        await s.commit()


async def grant_permission(role: str, perm: str) -> None:
    async with SessionLocal() as s:
        await s.merge(RolePermission(role=role, perm=perm))
        await s.commit()


# ---------------------------------------------------------------- AC8–AC10: nhắc giờ


async def test_ac8_ac10_reminder_boundaries_to_the_second_and_parallel_cron_sends_once(
    admin, staff, people
):
    hv = await people("QA Hội Viên Nhắc Biên")
    ep = await device(hv.client)
    exact = await member_block(staff, admin, hv, hour=18)  # created_at đúng start − 60'
    after = await member_block(staff, admin, hv, hour=18)  # created_at trễ 1 giây → không nhắc
    edge = await member_block(staff, admin, hv, hour=18)  # biên 15 phút
    start = await start_of(exact["code"])
    await _backdate(exact["code"], start - timedelta(minutes=60))
    await _backdate(after["code"], start - timedelta(minutes=60) + timedelta(seconds=1))
    await _backdate(edge["code"], start - timedelta(hours=3))
    await flush()
    PUSH.clear()

    async def run(now):
        await member_area.send_reminders(now)
        await testing.drain(ENQUEUED_JOBS)

    def bodies_for(order_code: str) -> list[str]:
        return [s.body for s in to(ep) if order_code in s.body]

    await run(start - timedelta(minutes=61))
    assert PUSH.sent == [], "chưa tới mốc 60 phút"
    # chạy song song 3 lần: mỗi khối chỉ một thông báo
    await asyncio.gather(
        *[member_area.send_reminders(start - timedelta(minutes=45)) for _ in range(3)]
    )
    await testing.drain(ENQUEUED_JOBS)
    assert len(bodies_for(exact["order_code"])) == 1, (
        "đúng mốc created_at = start − 60' phải nhắc, một lần"
    )
    assert bodies_for(after["order_code"]) == [], "đặt trễ 1 giây sau mốc thì không nhắc (AC10)"
    n_edge = len(bodies_for(edge["order_code"]))
    assert n_edge == 1
    # Biên 15 phút: còn đúng 15:00 → bỏ; vừa quá một giây (15:01) → đã nhắc từ trước, không thêm
    await run(start - timedelta(minutes=15))
    await run(start - timedelta(minutes=15, seconds=1))
    assert len(bodies_for(exact["order_code"])) == 1 and len(bodies_for(edge["order_code"])) == 1
    assert_no_identity(PUSH.sent, hv.phone, "QA Hội Viên Nhắc Biên")


async def test_ac10_catch_up_after_worker_downtime_only_while_more_than_15_minutes_remain(
    admin, staff, people
):
    hv = await people("QA Hội Viên Nhắc Bù")
    ep = await device(hv.client)
    one = await member_block(staff, admin, hv, hour=18)
    two = await member_block(staff, admin, hv, hour=18)
    start = await start_of(one["code"])
    for b in (one, two):
        await _backdate(b["code"], start - timedelta(hours=5))
    await flush()
    PUSH.clear()
    # Worker dừng suốt khung 17:00–17:44, chạy lại lúc start − 15'01'': còn hơn 15 phút → nhắc bù
    await member_area.send_reminders(start - timedelta(minutes=15, seconds=1))
    await testing.drain(ENQUEUED_JOBS)
    assert len(to(ep)) == 2, [s.body for s in to(ep)]
    PUSH.clear()
    # Đã quá: còn đúng 15 phút, 10 phút, buổi đã bắt đầu → bỏ, không thêm gì
    for delta in (timedelta(minutes=15), timedelta(minutes=10), timedelta(minutes=-1)):
        await member_area.send_reminders(start - delta)
    await testing.drain(ENQUEUED_JOBS)
    assert PUSH.sent == []


async def test_ac9_ac11_member_without_device_still_gets_the_inbox_text_but_nothing_is_sent(
    admin, staff, people
):
    hv = await people("QA Hội Viên Chưa Bật")
    b = await member_block(staff, admin, hv, hour=18)
    start = await start_of(b["code"])
    await _backdate(b["code"], start - timedelta(hours=2))
    await flush()
    PUSH.clear()
    before = len(PUSH.attempts)
    await member_area.send_reminders(start - timedelta(minutes=60))
    await testing.drain(ENQUEUED_JOBS)
    assert PUSH.sent == [] and len(PUSH.attempts) == before
    texts = await inbox_texts(hv.customer_id, "booking.reminder")
    assert texts == [f"{b['court']['name']} · 18h–19h hôm nay · {b['order_code']}"]


# ---------------------------------------------------------------- AC12–AC14: đơn thay đổi và thanh toán


async def test_ac12_guest_block_and_rejected_moves_send_nothing_two_blocks_two_pushes(
    admin, staff, people
):
    hv = await people("QA Hội Viên Đổi Hai Khối")
    ep = await device(hv.client)
    order = await member_order(admin, member(hv.code), 11, days=2)
    guest = await member_order(admin, temp("QA Khách Vãng Lai"), 11)
    target = await new_court(admin)
    await flush()
    PUSH.clear()
    first, second = sorted(order["bookings"], key=lambda b: b["code"])
    for b in (first, second):
        r = await admin.post(
            f"{BK}/items/{b['code']}/move",
            json={"resource_code": target["code"], "reason": "QA đổi sân", "version": b["version"]},
            headers=idem(),
        )
        assert r.status_code == 200, r.text
        await flush()
    sent = to(ep)
    assert len(sent) == 2 and len({s.tag for s in sent}) == 2 and len({s.body for s in sent}) == 2
    assert all(s.title == "Buổi chơi đã được đổi" for s in sent)
    # Khối của khách không tài khoản: đổi sân không push cho ai
    PUSH.clear()
    g = guest["bookings"][0]
    r = await admin.post(
        f"{BK}/items/{g['code']}/move",
        json={
            "resource_code": (await new_court(admin))["code"],
            "reason": "QA",
            "version": g["version"],
        },
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    await flush()
    assert PUSH.sent == []
    # Đổi bị từ chối (sai phiên bản) không được push
    r = await admin.post(
        f"{BK}/items/{first['code']}/move",
        json={"resource_code": (await new_court(admin))["code"], "reason": "QA", "version": 0},
        headers=idem(),
    )
    assert r.status_code >= 400
    await flush()
    assert PUSH.sent == []
    assert_no_identity(sent, hv.phone, "QA Hội Viên Đổi Hai Khối")


async def test_ac14_two_collect_transactions_two_pushes_with_correct_totals(admin, staff, people):
    hv = await people("QA Hội Viên Thu Hai Lượt")
    ep = await device(hv.client)
    order = await member_order(admin, member(hv.code), 8, days=3)
    blocks = sorted(order["bookings"], key=lambda b: b["code"])
    amounts = [b["payment"]["amount"] for b in blocks]
    await flush()
    PUSH.clear()
    r = await staff.post(
        f"{BK}/items/{blocks[0]['code']}/collect", json={"method": "cash"}, headers=idem()
    )
    assert r.status_code == 200, r.text
    await flush()
    r = await staff.post(
        f"{BK}/orders/{order['order_code']}/collect", json={"method": "cash"}, headers=idem()
    )
    assert r.status_code == 200, r.text
    await flush()
    sent = to(ep)
    oc = order["order_code"]
    assert [s.body for s in sent] == [
        f"{oc} · {vnd(amounts[0])} đ · tiền mặt",
        f"{oc} · {vnd(amounts[1] + amounts[2])} đ · tiền mặt",
    ], [s.body for s in sent]
    assert len(sent) == 2 and sent[0].tag != sent[1].tag
    assert all(s.title == "Đã ghi nhận thanh toán" for s in sent)


# ---------------------------------------------------------------- AC17–AC20: nhân viên theo quyền


async def test_ac17_online_booking_goes_to_calendar_viewers_only_follows_permission_and_hides_identity(
    admin, staff, customer, anon
):
    admin_ep, staff_ep, cust_ep = await device(admin), await device(staff), await device(customer)
    court = await new_court(admin)
    name, phone = "QA Khách Bí Mật Họ", "0867654321"
    r = await checkout(anon, [(court["code"], 15)], phone=phone, name=name)
    assert r.status_code == 201, r.text
    co = r.json()
    PUSH.clear()
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    await flush()
    titles = lambda ep: [s.title for s in to(ep)]  # noqa: E731
    assert "Đặt online mới" in titles(admin_ep) and "Đặt online mới" in titles(staff_ep)
    assert to(cust_ep) == [], "khách hàng thường không nhận thông báo nhân viên"
    assert_no_identity(PUSH.sent, phone, name)
    # Gỡ quyền xem lịch của NV: không nhận nữa dù thiết bị còn
    await drop_permission("staff", "booking.calendar.view")
    try:
        co2 = (
            await checkout(anon, [(court["code"], 18)], phone="0867654322", name="QA Khách Hai")
        ).json()
        PUSH.clear()
        assert await simulate(admin, co2["pay_ref"], co2["amount"]) == "applied"
        await flush()
        assert "Đặt online mới" in titles(admin_ep) and to(staff_ep) == []
    finally:
        await grant_permission("staff", "booking.calendar.view")


async def test_ac18_qr_received_needs_collect_permission_and_cash_never_notifies_staff(
    admin, staff, people
):
    hv = await people("QA Hội Viên QR Quyền")
    admin_ep, staff_ep = await device(admin), await device(staff)
    o1 = await member_order(admin, member(hv.code), 13, days=1)
    o2 = await member_order(admin, member(hv.code), 14, days=1)
    t1 = sum(b["payment"]["amount"] for b in o1["bookings"])
    t2 = sum(b["payment"]["amount"] for b in o2["bookings"])
    await flush()
    PUSH.clear()
    assert await simulate(admin, o1["order_code"].replace("-", ""), t1) == "applied"
    await flush()
    for ep in (admin_ep, staff_ep):
        assert [s.title for s in to(ep)].count("Đã nhận tiền QR") == 1
    await drop_permission("staff", "booking.collect")
    try:
        PUSH.clear()
        assert await simulate(admin, o2["order_code"].replace("-", ""), t2) == "applied"
        await flush()
        assert [s.title for s in to(admin_ep)].count("Đã nhận tiền QR") == 1 and to(staff_ep) == []
    finally:
        await grant_permission("staff", "booking.collect")
    # Thu tiền mặt không báo cho nhân viên
    o3 = await member_order(admin, member(hv.code), 15, days=1)
    PUSH.clear()
    r = await admin.post(
        f"{BK}/orders/{o3['order_code']}/collect", json={"method": "cash"}, headers=idem()
    )
    assert r.status_code == 200, r.text
    await flush()
    assert not [s for ep in (admin_ep, staff_ep) for s in to(ep) if s.title == "Đã nhận tiền QR"]


async def test_ac19_all_three_review_outcomes_pushed_and_applied_is_silent(admin, staff, anon):
    admin_ep = await device(admin)
    court = await new_court(admin)
    for hour, delta in ((10, -5_000), (11, +5_000)):  # thiếu tiền, thừa tiền
        co = (
            await checkout(
                anon, [(court["code"], hour)], phone=f"08677000{hour}", name="QA Khách TV"
            )
        ).json()
        PUSH.clear()
        outcome = await simulate(admin, co["pay_ref"], co["amount"] + delta)
        await flush()
        assert outcome in ("partial", "refund_needed"), outcome
        [sent] = [s for s in to(admin_ep) if s.title == "Tiền về cần xử lý"]
        assert sent.body == f"{vnd(co['amount'] + delta)} đ · {messages.REVIEW_LABELS[outcome]}"
        assert sent.url == messages.MONEY_REVIEW_URL
    PUSH.clear()
    assert await simulate(admin, "BK77777777777", 99_000) == "unmatched"
    await flush()
    [sent] = [s for s in to(admin_ep) if s.title == "Tiền về cần xử lý"]
    assert sent.body == "99.000 đ · Không khớp mã"
    # Tiền về đủ (applied) không báo "cần xử lý"
    co = (
        await checkout(anon, [(court["code"], 16)], phone="0867700016", name="QA Khách Đủ")
    ).json()
    PUSH.clear()
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    await flush()
    assert not [s for s in to(admin_ep) if s.title == "Tiền về cần xử lý"]


async def test_ac20_locked_staff_receives_nothing_while_active_admin_still_does(admin, staff, anon):
    admin_ep, staff_ep = await device(admin), await device(staff)
    staff_uid = await user_of(staff_ep)
    court = await new_court(admin)
    co = (
        await checkout(anon, [(court["code"], 12)], phone="0867700012", name="QA Khách Khóa")
    ).json()
    async with SessionLocal() as s:
        await s.execute(update(User).where(User.id == staff_uid).values(is_active=False))
        await s.commit()
    try:
        PUSH.clear()
        assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
        assert await simulate(admin, "BK66666666666", 10_000) == "unmatched"
        await flush()
        assert to(staff_ep) == []
        assert {"Đặt online mới", "Tiền về cần xử lý"} <= {s.title for s in to(admin_ep)}
    finally:
        async with SessionLocal() as s:
            await s.execute(update(User).where(User.id == staff_uid).values(is_active=True))
            await s.commit()


# ---------------------------------------------------------------- AC16: danh sách kind có push


def test_ac16_push_kinds_are_exactly_the_specified_set():
    assert set(messages.PUSH_KINDS) == {
        "booking.reminder",
        "booking.moved",
        "booking.cancelled",
        "booking.paid",
        "room.join_requested",
        "room.join_approved",
        "room.join_rejected",
    }


async def test_ac16_other_notification_kinds_enqueue_no_push_job():
    ENQUEUED_JOBS.clear()
    for kind in (
        "room.invited",
        "room.host_assigned",
        "room.kicked",
        "record.approved",
        "record.rejected",
        "achievement.earned",
        "event.created",
        "totally.unknown",
    ):
        await events.publish(
            "member.notification_created", {"id": 1, "customer_id": 1, "kind": kind}
        )
    assert [j for j in ENQUEUED_JOBS if j[0] in testing.JOBS] == []


# ---------------------------------------------------------------- AC23: push lỗi không hỏng luồng chính


async def test_ac23_push_failures_and_a_raising_sender_never_break_the_main_flow(
    admin, anon, monkeypatch
):
    admin_ep = await device(admin)
    court = await new_court(admin)
    co = (
        await checkout(anon, [(court["code"], 19)], phone="0867700019", name="QA Khách Lỗi")
    ).json()
    PUSH.clear()
    PUSH.fail(admin_ep, 500)
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    await flush()
    assert await fail_count(admin_ep) >= 1, "lỗi gửi được ghi nhận"
    # Sender ném ngoại lệ thay vì trả kết quả: luồng chính vẫn xong, không ngoại lệ lan ra
    PUSH.fail(admin_ep, None)

    async def boom(*_a, **_k):
        raise RuntimeError("push service down")

    monkeypatch.setattr(PUSH, "send", boom)
    co2 = (
        await checkout(anon, [(court["code"], 20)], phone="0867700020", name="QA Khách Lỗi 2")
    ).json()
    assert await simulate(admin, co2["pay_ref"], co2["amount"]) == "applied"
    await flush()  # không được ném ngoại lệ
    async with SessionLocal() as s:
        codes = list(
            await s.scalars(select(Booking.code).where(Booking.order_code == co2["order_code"]))
        )
    assert codes, "booking vẫn được tạo khi tiền về"


async def test_reminder_inbox_row_keeps_payload_code_for_dedup(admin, staff, people):
    """Khóa chống trùng nhắc giờ là mã khối: mỗi khối đúng một dòng hộp thông báo kể cả khi cron chạy lại."""
    hv = await people("QA Hội Viên Khóa Nhắc")
    b = await member_block(staff, admin, hv, hour=18)
    start = await start_of(b["code"])
    await _backdate(b["code"], start - timedelta(hours=2))
    for now in (
        start - timedelta(minutes=60),
        start - timedelta(minutes=50),
        start - timedelta(minutes=20),
    ):
        await member_area.send_reminders(now)
    async with SessionLocal() as s:
        rows = list(
            await s.scalars(
                select(MemberNotification).where(
                    MemberNotification.customer_id == hv.customer_id,
                    MemberNotification.kind == "booking.reminder",
                )
            )
        )
    assert len(rows) == 1
