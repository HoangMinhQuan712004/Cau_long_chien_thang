# ruff: noqa: E501
"""QA T-054 (API, AC5–AC9): tìm phòng theo đúng mã booking ``GET /member-area/rooms?q=``.

Ưu tiên: JSON không lộ mã booking / SĐT / id hồ sơ ở mọi đường ra; giới hạn 30 lượt / phút / tài khoản (biên, song song,
lách bằng hoa-thường / khoảng trắng, danh sách thường không tính); phòng của Host không đủ điều kiện và mọi lý do "không tìm ra"
phải cho kết quả giống hệt nhau; phòng ``ended`` chỉ đọc.
"""

import asyncio
import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.members.models import Customer
from app.modules.play_rooms.models import PlayRoom
from tests import test_play_rooms as base
from tests.conftest import API, _rate_limit_backend, idem
from tests.helpers_booking import BK, new_court, today
from tests.test_play_history import add_match
from tests.test_play_rooms import MA, post, room_for

people = base.people
ROOMS = f"{MA}/rooms"
FD = f"{API}/front-desk"
BOOKING_CODE = re.compile(r"BK-\d{8}-\d{3}")
FORBIDDEN_KEYS = ("booking_code", "customer_id", "public_id", "phone", "email", "member_code")
NOTHING = "BK-20000101-999"


def code_of(r) -> str:
    return r.json()["detail"]["code"]


def keys_of(node) -> set[str]:
    out: set[str] = set()
    if isinstance(node, dict):
        for k, v in node.items():
            out.add(k)
            out |= keys_of(v)
    elif isinstance(node, list):
        for v in node:
            out |= keys_of(v)
    return out


async def get_rooms(client, **params):
    return await client.get(ROOMS, params=params)


async def set_room(room_id: int, **values) -> None:
    async with SessionLocal() as s:
        await s.execute(update(PlayRoom).where(PlayRoom.id == room_id).values(**values))
        await s.commit()


async def cancel_paid(admin, code: str, version: int = 2) -> None:
    r = await admin.post(
        f"{BK}/items/{code}/collect", json={"method": "cash", "version": 1}, headers=idem()
    )
    assert r.status_code == 200, r.text
    r = await admin.post(
        f"{FD}/items/{code}/cancel",
        json={"reason": "QA bảo trì", "version": version, "refund_confirmed": True},
        headers=idem(),
    )
    assert r.status_code == 200, r.text


def assert_no_leak(text: str, *, code: str | None, phones=()):
    assert not BOOKING_CODE.search(text), f"lộ mã booking: {BOOKING_CODE.search(text).group(0)}"
    if code:
        assert code not in text and code.lower() not in text.lower()
    for phone in phones:
        assert phone not in text and phone.lstrip("0") not in text.replace(" ", "")
    for key in FORBIDDEN_KEYS:
        assert f'"{key}"' not in text, key


# ---------------------------------------------------------------- AC7: không lộ mã / SĐT / id


async def test_ac7_no_booking_code_phone_or_profile_id_in_any_room_json(staff, admin, people):
    host, seeker = await people("QA Chủ Riêng Tư"), await people("QA Người Tìm Riêng Tư")
    made = await room_for(staff, admin, host.code)
    code, room = made["code"], made["room"]
    # Thêm yêu cầu xin vào + thành viên để thẻ có đủ khối dữ liệu
    asked = await post(seeker.client, f"/{room.id}/join-requests", {"version": room.version})
    assert asked.status_code == 200, asked.text

    for label, client in (("seeker", seeker.client), ("host", host.client)):
        listing = await get_rooms(client)
        found = await get_rooms(client, q=code)
        found_order = await get_rooms(client, q=code.rsplit("-", 1)[0])
        for name, r in (("list", listing), ("search-child", found), ("search-order", found_order)):
            assert r.status_code == 200, (label, name, r.text)
            assert_no_leak(r.text, code=code, phones=(host.phone, seeker.phone))
            assert not ({"booking_code", "customer_id", "public_id"} & keys_of(r.json())), (
                label,
                name,
            )
            for header, value in r.headers.items():
                assert code not in value, f"mã nằm trong header {header}"
    # Phản hồi lỗi cũng không nhắc mã
    assert_no_leak(
        (await get_rooms(seeker.client, q="BK-sai")).text, code=code, phones=(host.phone,)
    )
    closed = await set_room_closed_and_try_join(room.id, seeker, room.version)
    assert code not in closed.text


async def set_room_closed_and_try_join(room_id: int, who, version: int):
    await set_room(room_id, status="closed")
    return await post(who.client, f"/{room_id}/join-requests", {"version": version})


async def test_ac7_other_members_cannot_resolve_a_code_through_by_booking_or_detail(
    staff, admin, people
):
    host, other = await people("QA Chủ Dò"), await people("QA Người Dò")
    made = await room_for(staff, admin, host.code)
    code, room = made["code"], made["room"]
    r = await other.client.get(f"{ROOMS}/by-booking/{code}")
    assert r.status_code in (404, 403), "người khác không dò được phòng qua by-booking"
    assert str(room.id) not in r.text or r.status_code != 200
    detail = await other.client.get(f"{ROOMS}/{room.id}")
    assert detail.status_code == 200, detail.text
    assert_no_leak(detail.text, code=code, phones=(host.phone, other.phone))


# ---------------------------------------------------------------- "không tìm ra" giống hệt nhau


async def test_not_found_reasons_are_indistinguishable(staff, admin, people):
    seeker = await people("QA Người Dò Lý Do")
    ok_host, bad_host, cancelled_host, norooom_host = (
        await people("QA Host Tốt"),
        await people("QA Host Ngừng"),
        await people("QA Host Hủy"),
        await people("QA Host Chưa Phòng"),
    )
    ok = await room_for(staff, admin, ok_host.code)
    bad = await room_for(staff, admin, bad_host.code)
    cancelled = await room_for(staff, admin, cancelled_host.code)
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == bad_host.customer_id).values(is_active=False)
        )
        await s.commit()
    await cancel_paid(admin, cancelled["code"])
    # booking chưa có phòng: đặt mà không cho handler tạo phòng (hội viên khác, giờ khác)
    from tests.helpers_booking import book, member, safe_hour

    court = await new_court(admin)
    hour = await safe_hour()
    r = await book(staff, court["code"], hour, customer=member(norooom_host.code))
    assert r.status_code == 201, r.text
    no_room_code = r.json()["code"]

    async def shape(q):
        r = await get_rooms(seeker.client, q=q)
        return r.status_code, r.json(), r.headers.get("cache-control"), "etag" in r.headers

    assert (await get_rooms(seeker.client, q=ok["code"])).json()["items"], (
        "đối chứng: phòng tốt tìm ra"
    )
    reference = await shape(NOTHING)
    assert reference[0] == 200 and reference[1]["items"] == []
    for label, q in (
        ("host-ngung", bad["code"]),
        ("huy-khong-co-tran-xong", cancelled["code"]),
        ("chua-co-phong", no_room_code),
        ("sai-dinh-dang", "BK-123"),
        ("rong", ""),
    ):
        got = await shape(q)
        assert got[0] == reference[0] and got[2] == reference[2] and got[3] == reference[3], label
        assert got[1]["items"] == [], label
        # cả phần số liệu banner cũng không đổi theo lý do
        assert {k: v for k, v in got[1].items() if k != "items"} == {
            k: v for k, v in reference[1].items() if k != "items"
        }, label


async def test_hidden_even_with_a_finished_match_when_the_host_is_not_eligible(
    staff, admin, people
):
    host, seeker = await people("QA Host Ngừng Có Trận"), await people("QA Người Tìm Ngừng")
    made = await room_for(staff, admin, host.code)
    await add_match(
        made["room"].id, 1, [host.customer_id], [seeker.customer_id], status="finished", win="a"
    )
    assert (await get_rooms(seeker.client, q=made["code"])).json()["items"]
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == host.customer_id).values(is_active=False)
        )
        await s.commit()
    assert (await get_rooms(seeker.client, q=made["code"])).json()["items"] == []
    assert (await seeker.client.get(f"{ROOMS}/{made['room'].id}")).status_code == 404
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == host.customer_id).values(is_active=True)
        )
        await s.commit()
    assert (await get_rooms(seeker.client, q=made["code"])).json()["items"], (
        "Host hoạt động lại → tìm ra"
    )


# ---------------------------------------------------------------- giới hạn 30 lượt / phút


async def test_search_limit_boundary_invalid_codes_count_and_variants_cannot_bypass(people):
    _rate_limit_backend.clear()
    a, b = await people("QA Giới Hạn A"), await people("QA Giới Hạn B")
    variants = [NOTHING, NOTHING.lower(), f"  {NOTHING}  ", "BK-xx", "", "BK-20000101-998-01"]
    for i in range(30):
        r = await get_rooms(a.client, q=variants[i % len(variants)])
        assert r.status_code == 200, (i, r.text)
    r = await get_rooms(a.client, q=NOTHING)
    assert r.status_code == 429 and code_of(r) == "E-SEC-5", r.text
    assert 1 <= int(r.headers["Retry-After"]) <= 60
    # Lách bằng biến thể / scope / tham số khác vẫn bị chặn
    for params in (
        {"q": NOTHING.lower()},
        {"q": " " + NOTHING},
        {"q": NOTHING, "scope": "mine"},
        {"q": "x"},
    ):
        assert (await get_rooms(a.client, **params)).status_code == 429, params
    # Danh sách thường không tính và không bị chặn
    assert (await get_rooms(a.client)).status_code == 200
    assert (await get_rooms(a.client, scope="mine")).status_code == 200
    # Tài khoản khác (cùng IP) không bị ảnh hưởng
    assert (await get_rooms(b.client, q=NOTHING)).status_code == 200
    _rate_limit_backend.clear()
    assert (await get_rooms(a.client, q=NOTHING)).status_code == 200, "hết cửa sổ thì tìm lại được"


async def test_search_limit_holds_under_parallel_requests(people):
    _rate_limit_backend.clear()
    a = await people("QA Giới Hạn Song Song")
    res = await asyncio.gather(*[get_rooms(a.client, q=NOTHING) for _ in range(45)])
    codes = [r.status_code for r in res]
    assert codes.count(200) == 30 and codes.count(429) == 15, (codes.count(200), codes.count(429))
    assert all(code_of(r) == "E-SEC-5" for r in res if r.status_code == 429)
    _rate_limit_backend.clear()


# ---------------------------------------------------------------- AC8: phòng đã kết thúc


async def test_ac8_ended_rooms_are_read_only_labelled_and_show_the_tier_range(staff, admin, people):
    host, seeker = await people("QA Host Kết Thúc"), await people("QA Người Xem Kết Thúc")
    made = await room_for(staff, admin, host.code)
    room = made["room"]
    asked = await post(seeker.client, f"/{room.id}/join-requests", {"version": room.version})
    assert asked.status_code == 200
    # 1) đóng hẳn
    await set_room(room.id, status="closed")
    card = (await get_rooms(seeker.client, q=made["code"])).json()["items"][0]
    assert card["status"] == "ended" and card["id"] == room.id
    assert (
        card["my_join_block"] is None
        and card["my_invite_id"] is None
        and card["my_join_pending"] is False
    )
    assert "tier_range" in card, "thẻ hiện khoảng hạng (T-050)"
    again = await post(seeker.client, f"/{room.id}/join-requests", {"version": room.version})
    assert again.status_code == 409 and code_of(again) == "E-ROOM-1"
    # Chỉ xin vào, chưa từng ở trong phòng: không xem được; Host xem được (AC10)
    assert card["can_view"] is False
    assert (await seeker.client.get(f"{ROOMS}/{room.id}")).status_code == 404
    assert (await host.client.get(f"{ROOMS}/{room.id}")).status_code == 200, "Host vào xem được"
    # 2) hết giờ + ân hạn nhưng job chưa kịp đóng
    await set_room(
        room.id,
        status="open",
        start_at=datetime.now(UTC) - timedelta(hours=5),
        end_at=datetime.now(UTC) - timedelta(hours=4),
    )
    card = (await get_rooms(seeker.client, q=made["code"])).json()["items"][0]
    assert card["status"] == "ended"
    assert (
        card["play_date"]
        == (datetime.now(UTC) - timedelta(hours=5)).astimezone(settings.tz).date().isoformat()
    )
    # 3) danh sách thường không hiện phòng đã kết thúc
    listed = (await get_rooms(seeker.client)).json()["items"]
    assert room.id not in [x["id"] for x in listed] and all(x["status"] == "open" for x in listed)


async def test_cancelled_booking_with_finished_match_is_found_as_ended_and_without_it_is_not(
    staff, admin, people
):
    host, mate, seeker = (
        await people("QA Host Hủy Có Trận"),
        await people("QA Đồng Đội Hủy"),
        await people("QA Người Tìm Hủy"),
    )
    with_match = await room_for(staff, admin, host.code)
    without = await room_for(staff, admin, mate.code)
    await add_match(
        with_match["room"].id, 1, [host.customer_id], [mate.customer_id], status="finished", win="a"
    )
    await cancel_paid(admin, with_match["code"])
    await cancel_paid(admin, without["code"])
    found = (await get_rooms(seeker.client, q=with_match["code"])).json()["items"]
    assert [x["id"] for x in found] == [with_match["room"].id] and found[0]["status"] == "ended"
    assert found[0]["my_join_block"] is None
    assert (await get_rooms(seeker.client, q=without["code"])).json()["items"] == []
    listed = [x["id"] for x in (await get_rooms(seeker.client)).json()["items"]]
    assert with_match["room"].id not in listed and without["room"].id not in listed


# ---------------------------------------------------------------- AC9 + quyền + banner


async def test_ac9_banner_and_normal_list_are_unaffected_by_q_and_access_rules(
    anon, customer, staff, admin, people
):
    host, seeker = await people("QA Host Banner"), await people("QA Người Banner")
    made = await room_for(staff, admin, host.code)
    plain = (await get_rooms(seeker.client)).json()
    searched = (await get_rooms(seeker.client, q=made["code"])).json()
    banner = {k: v for k, v in plain.items() if k != "items"}
    assert {k: v for k, v in searched.items() if k != "items"} == banner, (
        "số liệu banner là của hôm nay, không theo q"
    )
    assert made["room"].id in [x["id"] for x in plain["items"]]
    assert all(
        x["status"] == "open" and x["play_date"] == today().isoformat() for x in plain["items"]
    )
    # q bị bỏ qua tab: scope=mine với q vẫn ra phòng của người khác
    assert (await get_rooms(seeker.client, q=made["code"], scope="mine")).json()["items"]
    # Quyền
    assert (await get_rooms(anon, q=made["code"])).status_code == 401
    r = await get_rooms(customer, q=made["code"])
    assert r.status_code in (401, 403), "tài khoản chưa là hội viên không tìm được"
    assert (await get_rooms(admin, q=made["code"])).status_code in (401, 403)


async def test_malformed_and_hostile_q_values_never_error(people):
    _rate_limit_backend.clear()
    hv = await people("QA Q Xấu")
    hostile = [
        "BK-20261107-001'; DROP TABLE play_room;--",
        "BK-２０２６１１０７-００１",  # chữ số full-width
        "BK-20261107-001\nBK-20261107-002",
        "BK-20261107-001-01-02",
        "%",
        "_" * 200,
        "BK-99999999-999",
        "BK-20261107-0011",
        "\u0000",
    ]
    for q in hostile:
        r = await get_rooms(hv.client, q=q)
        assert r.status_code == 200 and r.json()["items"] == [], (q, r.status_code, r.text[:200])
    # q lặp: một lượt tìm
    r = await hv.client.get(f"{ROOMS}?q={NOTHING}&q={NOTHING.lower()}")
    assert r.status_code == 200
    _rate_limit_backend.clear()
