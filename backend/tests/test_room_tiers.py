"""T-031: khoảng hạng phòng chơi – chọn lúc đặt trong khu hội viên, chặn khi vào phòng."""

from sqlalchemy import select, update

from app.core.db import SessionLocal
from app.modules.booking_engine import api as engine
from app.modules.booking_engine.models import Booking, BookingOrder, Checkout
from app.modules.members.models import Customer
from app.modules.play_rooms.models import PlayRoom
from tests import test_play_rooms as base
from tests.helpers_booking import new_court
from tests.helpers_web import checkout, simulate
from tests.test_member_home import member_checkout
from tests.test_play_rooms import ROOMS, code_of, detail, post, room_for

people = base.people  # fixture dùng chung (hội viên có tài khoản liên kết)


async def set_tier(customer_id: int, tier: str | None) -> None:
    async with SessionLocal() as s:
        await s.execute(update(Customer).where(Customer.id == customer_id).values(tier=tier))
        await s.commit()


async def set_range(room_id: int, low: str | None, high: str | None) -> None:
    async with SessionLocal() as s:
        await s.execute(
            update(PlayRoom).where(PlayRoom.id == room_id).values(min_tier=low, max_tier=high)
        )
        await s.commit()


async def v(client, room_id: int) -> int:
    return (await detail(client, room_id))["version"]


# ------------------------------------------------------------------ AC2, AC3: đặt -> đơn -> phòng


async def test_member_checkout_range_goes_to_every_room_of_the_order(admin, people):
    host = await people("Chủ Sân Hạng")
    court = await new_court(admin)
    r = await member_checkout(host.client, court["code"], 9, min_tier="Khá", max_tier="Bán chuyên")
    assert r.status_code == 201, r.text
    co = r.json()
    assert co["status"] == "pending"
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    while await engine.publish_outbox(SessionLocal):
        pass
    async with SessionLocal() as s:
        order = await s.scalar(select(BookingOrder).where(BookingOrder.code == co["order_code"]))
        assert (order.min_tier, order.max_tier) == ("Khá", "Bán chuyên")
        codes = list(await s.scalars(select(Booking.code).where(Booking.order_id == order.id)))
        rooms = list(await s.scalars(select(PlayRoom).where(PlayRoom.booking_code.in_(codes))))
    assert rooms and {(x.min_tier, x.max_tier) for x in rooms} == {("Khá", "Bán chuyên")}
    d = await detail(host.client, rooms[0].id)
    assert d["tier_range"] == {"min": "Khá", "max": "Bán chuyên"}
    assert d["my_role"] == "host" and d["my_join_block"] is None


async def test_multi_block_order_and_open_ranges(admin, people):
    host = await people()
    court = await new_court(admin)
    body = {
        "slots": [
            {"resource_code": court["code"], "start_hour": 9},
            {"resource_code": court["code"], "start_hour": 14},
        ],
        "min_tier": "Trung bình",
    }
    r = await member_checkout(host.client, court["code"], 9, **body)
    assert r.status_code == 201, r.text
    co = r.json()
    assert len(co["items"]) == 2
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    while await engine.publish_outbox(SessionLocal):
        pass
    async with SessionLocal() as s:
        rooms = list(
            await s.scalars(
                select(PlayRoom).where(PlayRoom.booking_code.in_([i["code"] for i in co["items"]]))
            )
        )
    assert len(rooms) == 2
    assert {(x.min_tier, x.max_tier) for x in rooms} == {("Trung bình", None)}  # khoảng mở


async def test_invalid_ranges_and_public_checkout_ignores_range(anon, admin, people):
    host = await people()
    court = await new_court(admin)
    r = await member_checkout(host.client, court["code"], 10, min_tier="Khá", max_tier="Yếu")
    assert r.status_code == 422 and code_of(r) == "E-ROOM-14"
    assert r.json()["detail"]["message"] == "Khoảng hạng không hợp lệ."
    r = await member_checkout(host.client, court["code"], 10, min_tier="Siêu sao")
    assert r.status_code == 422  # tên hạng lạ (validation)

    # Đặt công khai (không as_member): khoảng hạng bị bỏ qua -> phòng không giới hạn
    r = await checkout(anon, [(court["code"], 11)], min_tier="Khá", max_tier="Khá")
    assert r.status_code == 201, r.text
    async with SessionLocal() as s:
        row = await s.scalar(select(Checkout).where(Checkout.pay_ref == r.json()["pay_ref"]))
    assert (row.min_tier, row.max_tier) == (None, None)


# ------------------------------------------------------------------ AC4, AC6: chặn 4 chỗ


async def test_join_invite_approve_accept_are_blocked_outside_range(staff, admin, people):
    host = await people("Chủ Phòng Hạng")
    low = await people("Hạng Thấp")
    unranked = await people("Chưa Xếp")
    good = await people("Hạng Khá")
    invitee = await people("Được Mời")
    await set_tier(host.customer_id, "Yếu")  # Host ngoài khoảng vẫn là Host (AC6)
    await set_tier(low.customer_id, "Trung bình yếu")
    await set_tier(unranked.customer_id, None)
    await set_tier(good.customer_id, "Khá")
    await set_tier(invitee.customer_id, "Chuyên nghiệp")
    room = (await room_for(staff, admin, host.code))["room"]
    await set_range(room.id, "Khá", "Bán chuyên")

    # Danh sách sân + chi tiết: khoảng hạng và lý do không vào được
    cards = (await low.client.get(ROOMS)).json()["items"]
    card = next(c for c in cards if c["id"] == room.id)
    assert card["tier_range"] == {"min": "Khá", "max": "Bán chuyên"}
    assert card["my_join_block"] == "out_of_range"
    assert (await detail(unranked.client, room.id))["my_join_block"] == "unranked"
    assert (await detail(good.client, room.id))["my_join_block"] is None
    assert (await detail(host.client, room.id))["my_join_block"] is None  # đã trong phòng

    # Xin vào
    r = await post(
        low.client, f"/{room.id}/join-requests", {"version": await v(host.client, room.id)}
    )
    assert r.status_code == 409 and code_of(r) == "E-ROOM-13"
    assert r.json()["detail"]["message"] == "Phòng chỉ dành cho hạng Khá–Bán chuyên."
    r = await post(
        unranked.client, f"/{room.id}/join-requests", {"version": await v(host.client, room.id)}
    )
    assert r.status_code == 409 and r.json()["detail"]["message"] == (
        "Phòng chỉ dành cho hạng Khá–Bán chuyên. Liên hệ quầy để được xếp hạng."
    )
    r = await post(
        good.client, f"/{room.id}/join-requests", {"version": await v(host.client, room.id)}
    )
    assert r.status_code == 200, r.text

    # Host thấy hạng người xin; người xin đổi hạng ra ngoài khoảng -> duyệt bị chặn
    d = await detail(host.client, room.id)
    [req] = d["join_requests"]
    assert req["tier"] == "Khá"
    await set_tier(good.customer_id, "Yếu")
    r = await post(
        host.client, f"/{room.id}/join-requests/{req['id']}/approve", {"version": d["version"]}
    )
    assert r.status_code == 409 and code_of(r) == "E-ROOM-13"
    await set_tier(good.customer_id, "Bán chuyên")  # biên trên
    r = await post(
        host.client, f"/{room.id}/join-requests/{req['id']}/approve", {"version": d["version"]}
    )
    assert r.status_code == 200, r.text

    # Mời theo SĐT: ngoài khoảng -> E-ROOM-13 (không nói hạng của người được mời)
    r = await post(
        host.client,
        f"/{room.id}/invites",
        {"phone": invitee.phone, "version": await v(host.client, room.id)},
    )
    assert r.status_code == 409 and code_of(r) == "E-ROOM-13"
    assert "Chuyên nghiệp" not in r.text
    await set_tier(invitee.customer_id, "Khá")  # biên dưới
    r = await post(
        host.client,
        f"/{room.id}/invites",
        {"phone": invitee.phone, "version": await v(host.client, room.id)},
    )
    assert r.status_code == 200, r.text
    # Nhận lời sau khi hạng đổi ra ngoài -> chặn; về lại trong khoảng -> vào được
    invite_id = (await detail(invitee.client, room.id))["my_invite_id"]
    await set_tier(invitee.customer_id, None)
    r = await post(invitee.client, f"/invites/{invite_id}/accept")
    assert r.status_code == 409 and code_of(r) == "E-ROOM-13"
    await set_tier(invitee.customer_id, "Khá")
    r = await post(invitee.client, f"/invites/{invite_id}/accept")
    assert r.status_code == 200, r.text

    # Người đã trong phòng đổi hạng ra ngoài: không bị đẩy ra (AC6)
    await set_tier(good.customer_id, "Yếu")
    d = await detail(host.client, room.id)
    assert len(d["members"]) == 3 and d["my_role"] == "host"
    assert (await detail(good.client, room.id))["my_role"] == "member"


async def test_open_range_messages_and_counter_room_unlimited(staff, admin, people):
    host, guest = await people(), await people()
    await set_tier(guest.customer_id, "Trung bình")
    room = (await room_for(staff, admin, host.code))["room"]  # đặt quầy -> không giới hạn
    d = await detail(guest.client, room.id)
    assert d["tier_range"] is None and d["my_join_block"] is None

    await set_range(room.id, "Khá", None)
    r = await post(
        guest.client, f"/{room.id}/join-requests", {"version": await v(host.client, room.id)}
    )
    assert r.json()["detail"]["message"] == "Phòng chỉ dành cho hạng từ Khá trở lên."
    await set_range(room.id, None, "Trung bình -")
    r = await post(
        guest.client, f"/{room.id}/join-requests", {"version": await v(host.client, room.id)}
    )
    assert r.json()["detail"]["message"] == "Phòng chỉ dành cho hạng đến Trung bình -."
    await set_range(room.id, None, "Trung bình")  # biên
    r = await post(
        guest.client, f"/{room.id}/join-requests", {"version": await v(host.client, room.id)}
    )
    assert r.status_code == 200, r.text
