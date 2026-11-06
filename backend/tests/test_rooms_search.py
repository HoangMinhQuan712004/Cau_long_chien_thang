"""T-054: tìm phòng theo đúng mã booking (mọi ngày, mọi phòng), ``status: ended``, ``play_date``,
giới hạn 30 lượt / phút, không lộ mã booking."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.members.models import Customer
from app.modules.play_rooms import lifecycle
from app.modules.play_rooms.models import PlayRoom
from tests import test_play_rooms as base
from tests.conftest import API, idem
from tests.helpers_booking import BK, book, book_order, member, new_court, safe_hour, temp, today
from tests.test_play_history import add_match
from tests.test_play_rooms import MA, post, room_for

people = base.people

ROOMS = f"{MA}/rooms"
FD = f"{API}/front-desk"


async def search(client, q: str, **params):
    r = await client.get(ROOMS, params={"q": q, **params})
    assert r.status_code == 200, r.text
    return r


async def items(client, q: str, **params) -> list[dict]:
    return (await search(client, q, **params)).json()["items"]


async def move_room(room_id: int, days: int, **values) -> datetime:
    start = datetime.now(UTC) + timedelta(days=days)
    async with SessionLocal() as s:
        await s.execute(
            update(PlayRoom)
            .where(PlayRoom.id == room_id)
            .values(start_at=start, end_at=start + timedelta(hours=1), **values)
        )
        await s.commit()
    return start


async def cancel_paid(admin, code: str) -> None:
    r = await admin.post(
        f"{BK}/items/{code}/collect", json={"method": "cash", "version": 1}, headers=idem()
    )
    assert r.status_code == 200, r.text
    r = await admin.post(
        f"{FD}/items/{code}/cancel",
        json={"reason": "Sân bảo trì", "version": 2, "refund_confirmed": True},
        headers=idem(),
    )
    assert r.status_code == 200, r.text


async def test_find_by_child_code_for_anyone_and_leak_nothing(staff, admin, people):
    host, other = await people("Chủ Phòng"), await people("Người Tìm")
    made = await room_for(staff, admin, host.code)
    code, room = made["code"], made["room"]

    r = await search(other.client, code)
    assert r.headers["cache-control"] == "no-store" and "etag" not in r.headers
    d = r.json()
    assert [i["id"] for i in d["items"]] == [room.id]
    card = d["items"][0]
    assert card["status"] == "open" and card["play_date"] == today().isoformat()
    assert card["is_mine"] is False
    # Thẻ và cả JSON không có mã booking, SĐT, id hồ sơ
    assert code not in r.text and host.phone not in r.text
    assert "booking_code" not in r.text and "customer_id" not in r.text

    # Bỏ khoảng trắng, không phân biệt hoa thường; bỏ qua scope
    assert [i["id"] for i in await items(other.client, f" {code.lower()} ")] == [room.id]
    assert [i["id"] for i in await items(other.client, code, scope="mine")] == [room.id]


async def test_order_code_finds_every_block_in_time_order(staff, admin, people):
    host, other = await people("Chủ Đơn"), await people("Người Tìm")
    a, b = await new_court(admin), await new_court(admin)
    hour = await safe_hour()
    r = await book_order(
        staff, [(a["code"], hour, hour + 1), (b["code"], hour, hour + 1)], member(host.code)
    )
    assert r.status_code == 201, r.text
    order = r.json()
    codes = [x["code"] for x in order["bookings"]]
    async with SessionLocal() as s:
        await lifecycle.ensure_for_codes(s, codes)
        await s.commit()
        rooms = {
            x.booking_code: x
            for x in await s.scalars(select(PlayRoom).where(PlayRoom.booking_code.in_(codes)))
        }
    await move_room(rooms[codes[0]].id, days=2)

    found = await items(other.client, order["order_code"])
    assert [i["id"] for i in found] == [rooms[codes[1]].id, rooms[codes[0]].id]
    assert [i["id"] for i in await items(other.client, codes[0])] == [rooms[codes[0]].id]


async def test_bad_format_partial_and_unknown_codes_return_nothing(staff, admin, people):
    host = await people("Chủ Phòng")
    made = await room_for(staff, admin, host.code)
    code = made["code"]
    normal = (await host.client.get(ROOMS)).json()
    for q in (
        "",
        "BK",
        code[:-1],  # thiếu ký tự
        code + "9",
        code.replace("BK-", ""),
        "BK-20261106-00%",
        "BK-________-___",
        "' OR 1=1 --",
        "BK-20000101-999",
        "BK-20000101-999-01",
        "٣" * 8,
    ):
        d = (await search(host.client, q)).json()
        assert d["items"] == [], q
        # Số liệu banner vẫn của hôm nay
        assert (d["all_count"], d["mine_count"]) == (normal["all_count"], normal["mine_count"])


async def test_other_days_upcoming_and_ended(staff, admin, people):
    host, other = await people("Chủ Phòng"), await people("Người Tìm")
    made = await room_for(staff, admin, host.code)
    code, room = made["code"], made["room"]

    # Sắp tới: thẻ thường, không ở danh sách hôm nay
    start = await move_room(room.id, days=3)
    card = (await items(other.client, code))[0]
    assert card["status"] == "open" and card["phase"] == "upcoming"
    assert card["play_date"] == start.astimezone(settings.tz).date().isoformat()
    assert room.id not in [i["id"] for i in (await other.client.get(ROOMS)).json()["items"]]

    # Xin vào rồi phòng đóng: không còn trạng thái chờ, không xin vào được, vẫn xem được
    r = await post(other.client, f"/{room.id}/join-requests", {"version": card["version"]})
    assert r.status_code == 200, r.text
    assert (await items(other.client, code))[0]["my_join_pending"] is True
    start = await move_room(room.id, days=-3, status="closed")
    card = (await items(other.client, code))[0]
    assert card["status"] == "ended"
    assert card["play_date"] == start.astimezone(settings.tz).date().isoformat()
    assert card["my_join_pending"] is False and card["my_join_block"] is None
    assert card["my_invite_id"] is None
    assert (await other.client.get(f"{ROOMS}/{room.id}")).status_code == 200
    r = await post(other.client, f"/{room.id}/leave", {"version": card["version"]})
    assert r.status_code == 409

    # Hết giờ mà job chưa kịp đóng cũng là ended
    await move_room(room.id, days=-1, status="open")
    assert (await items(other.client, code))[0]["status"] == "ended"


async def test_hidden_rooms_look_like_unknown_codes(staff, admin, people):
    host, other = await people("Chủ Phòng"), await people("Người Tìm")

    # Host không đủ điều kiện
    made = await room_for(staff, admin, host.code)
    assert await items(other.client, made["code"])
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.phone == host.phone).values(is_active=False)
        )
        await s.commit()
    assert await items(other.client, made["code"]) == []
    async with SessionLocal() as s:
        await s.execute(update(Customer).where(Customer.phone == host.phone).values(is_active=True))
        await s.commit()

    # Booking chưa có phòng (khách chưa có hồ sơ)
    court = await new_court(admin)
    hour = await safe_hour()
    r = await book(staff, court["code"], hour, customer=temp(f"Tạm {uuid.uuid4().hex[:4]}"))
    assert r.status_code == 201, r.text
    assert await items(other.client, r.json()["code"]) == []


async def test_cancelled_rooms_need_a_finished_match(staff, admin, people):
    host, other = await people("Chủ Phòng"), await people("Người Tìm")
    empty = await room_for(staff, admin, host.code)
    played = await room_for(staff, admin, host.code)
    await add_match(played["room"].id, 1, [host.customer_id], [-1], status="finished", win="a")
    await cancel_paid(admin, empty["code"])
    await cancel_paid(admin, played["code"])

    assert await items(other.client, empty["code"]) == []
    card = (await items(other.client, played["code"]))[0]
    assert card["id"] == played["room"].id and card["status"] == "ended"
    assert card["my_join_block"] is None
    # Danh sách thường không có cả hai
    listed = [i["id"] for i in (await other.client.get(ROOMS)).json()["items"]]
    assert empty["room"].id not in listed and played["room"].id not in listed


async def test_search_limit_is_per_account_and_only_for_search(people):
    a, b = await people("Tìm Nhiều"), await people("Người Khác")
    for _ in range(30):
        await search(a.client, "BK-20000101-999")
    r = await a.client.get(ROOMS, params={"q": "BK-20000101-999"})
    assert r.status_code == 429 and r.json()["detail"]["code"] == "E-SEC-5"
    assert int(r.headers["retry-after"]) >= 1
    # Sai định dạng cũng tính lượt
    r = await a.client.get(ROOMS, params={"q": "x"})
    assert r.status_code == 429
    # Người khác và danh sách thường không bị ảnh hưởng
    await search(b.client, "BK-20000101-999")
    r = await a.client.get(ROOMS)
    assert r.status_code == 200 and r.headers.get("etag")


async def test_normal_list_keeps_its_shape_and_etag(staff, admin, people):
    host = await people("Chủ Phòng")
    made = await room_for(staff, admin, host.code)
    r = await host.client.get(ROOMS)
    assert r.headers["cache-control"] == "no-cache, private" and r.headers["etag"]
    assert "no-store" not in r.headers["cache-control"]
    card = next(i for i in r.json()["items"] if i["id"] == made["room"].id)
    assert card["status"] == "open" and card["play_date"] == today().isoformat()
    assert made["code"] not in r.text
    again = await host.client.get(ROOMS, headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


async def test_search_requires_login(anon):
    assert (await anon.get(ROOMS, params={"q": "BK-20000101-999"})).status_code == 401
