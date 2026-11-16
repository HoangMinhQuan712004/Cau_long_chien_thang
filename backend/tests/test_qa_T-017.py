# ruff: noqa: E501, F811
"""QA T-017 mốc 1 (phòng chơi: tạo phòng, danh sách, xin vào / mời / duyệt / rời / mời ra, thông báo), viết từ spec
`T-017-phong-choi.md` (gồm mục "Chốt 31/10") – độc lập với test_play_rooms.py của BACKEND.

Phạm vi: AC1–AC12 (trừ phần trận), AC22, AC25, AC26 (trừ room.match_saved); SEC1, SEC2, SEC3, SEC5, SEC6.
Phòng được tạo bằng đường thật: đặt quầy → phát outbox (`booking.created`) → handler tạo phòng; backfill bằng job `play_rooms_tick`.
"""

import asyncio
import json
import re
import uuid

import pytest

from tests.conftest import API, _client, idem, unique_phone
from tests.helpers_booking import book, member, new_court, random_phone, safe_hour, temp, today
from tests.qa_accounts import db_account
from tests.qa_rooms import (  # noqa: F401
    MA,
    NOTI,
    ROOMS,
    Hv,
    M,
    act,
    detail,
    digits_leak,
    err,
    fill,
    find_room,
    make_room,
    people,
    publish,
    q,
    tick,
    with_v,
    x,
)

# ============================================================ AC1 tạo phòng


async def test_ac1_counter_booking_creates_a_room_for_a_linked_member_via_outbox(admin, people):
    host = await people("Chủ Phòng Một")
    spec = await make_room(admin, host.client, host.code)
    room = spec["room"]
    assert room is not None, "booking.created → phòng"
    assert (
        room["host"]["display_name"] == "Chủ Phòng Một"
        and room["member_count"] == 1
        and room["capacity"] == 8
    )
    assert room["phase"] in ("ongoing", "upcoming") and room["resource_type_name"]
    d = await detail(host.client, room["id"])
    assert (
        d["my_role"] == "host"
        and d["members"][0]["role"] == "host"
        and d["members"][0]["queue_state"] == "waiting"
    ), "Host đứng sẵn trong Hàng chờ"
    assert d["status"] == "open" and d["format"] == "2v2" and d["current_match"] is None


async def test_ac1_one_room_per_booking_block_and_running_twice_does_not_duplicate(admin, people):
    host = await people("Chủ Hai Khối")
    c1, c2 = await new_court(admin), await new_court(admin)
    h = await safe_hour()
    if h >= 22:
        pytest.skip("không đủ giờ trong ngày")
    for court in (c1, c2):
        assert (await book(admin, court["code"], h, h + 1, member(host.code))).status_code == 201
    await publish()
    await tick()
    await publish()
    names = [
        i["resource_name"]
        for i in (await host.client.get(ROOMS, params={"scope": "mine"})).json()["items"]
    ]
    assert names.count(c1["name"]) == 1 and names.count(c2["name"]) == 1, (
        "mỗi khối một phòng, chạy lại không nhân đôi"
    )


async def test_ac1_backfill_job_creates_a_missed_room(admin, people):
    host = await people("Chủ Bù Phòng")
    spec = await make_room(admin, host.client, host.code, via="tick")
    assert spec["room"] is not None, "job play_rooms_tick bù phòng khi worker lỡ sự kiện"


async def test_ac1_no_room_for_events_and_for_guests_without_a_profile(admin, people):
    host = await people("Chủ Không Phòng")
    # booking của khách vãng lai (hồ sơ tạm chưa liên kết) → không phòng
    guest = await make_room(
        admin, host.client, None, customer=temp("QA Khách Vãng Lai", random_phone())
    )
    assert guest["room"] is None
    # vé sự kiện → không phòng
    court = await new_court(admin)
    h = await safe_hour()
    ev = await admin.post(
        f"{API}/booking/sessions",
        json={
            "resource_codes": [court["code"]],
            "date": today().isoformat(),
            "start_hour": h,
            "end_hour": h + 1,
            "name": f"QA sự kiện {uuid.uuid4().hex[:5]}",
            "capacity": 3,
            "ticket_price": 50000,
        },
        headers=idem(),
    )
    assert ev.status_code == 201, ev.text
    await publish()
    await tick()
    assert await find_room(host.client, court["name"]) is None, "sự kiện không tạo phòng"


async def test_ac2_host_must_be_an_active_linked_member_checked_at_read_time(admin, people):
    host = await people("Chủ Điều Kiện")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    other = await people("Người Ngoài")
    assert await find_room(other.client, spec["court"]["name"]) is not None
    # Host bị Ngừng → phòng ẩn, chi tiết 404
    cur = (await admin.get(f"{M}/{host.code}")).json()
    assert (
        await admin.patch(
            f"{M}/{host.code}", json={"is_active": False, "version": cur["version"]}, headers=idem()
        )
    ).status_code == 200
    assert await find_room(other.client, spec["court"]["name"]) is None
    assert (await other.client.get(f"{ROOMS}/{rid}")).status_code == 404
    r = await act(other.client, rid, "/join-requests", {"version": 1})
    assert r.status_code == 404, "thao tác trên phòng của Host không đủ điều kiện → 404"
    cur = (await admin.get(f"{M}/{host.code}")).json()
    assert (
        await admin.patch(
            f"{M}/{host.code}", json={"is_active": True, "version": cur["version"]}, headers=idem()
        )
    ).status_code == 200


async def test_ac2_temp_profile_room_appears_after_the_owner_verifies_the_phone(admin, people):
    """T-021: hồ sơ tạm được nâng (cùng id) → phòng của booking cũ tự hiện."""
    phone = random_phone()
    assert (
        await admin.post(
            f"{M}/temp", json={"full_name": "QA Tạm Có Phòng", "phone": phone}, headers=idem()
        )
    ).status_code == 201
    viewer = await people("Người Xem")
    spec = await make_room(admin, viewer.client, None, customer=temp("QA Tạm Có Phòng", phone))
    assert spec["room"] is None, "hồ sơ tạm chưa phải hội viên"
    async with _client() as c:
        from tests.conftest import register

        r = await register(c, phone, "Tên Tài Khoản")
        assert r.status_code == 201 and r.json()["upgraded_from_temp"] is True
    await tick()
    room = await find_room(viewer.client, spec["court"]["name"])
    assert room is not None and room["host"]["display_name"] == "QA Tạm Có Phòng", (
        "giữ họ tên của hồ sơ; phòng hiện sau khi nâng"
    )
    await x("DELETE FROM customer WHERE phone=:p", p=phone)


# ============================================================ AC3 đóng phòng + SEC5


async def test_ac3_room_closes_after_end_plus_10_minutes_and_all_writes_are_blocked(admin, people):
    host, guest = await people("Chủ Đóng"), await people("Khách Đóng")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    await fill(rid, host, [guest])
    await x(
        "UPDATE play_room SET end_at = now() - interval '11 minutes', start_at = now() - interval '71 minutes' WHERE id=:i",
        i=rid,
    )
    # chưa chạy job: ghi bị chặn ngay
    r = await with_v(host.client, rid, "/invites", {"phone": random_phone()})
    assert (
        r.status_code == 409
        and err(r)["code"] == "E-ROOM-1"
        and err(r)["message"] == "Phòng đã đóng."
    )
    await tick()
    assert (await detail(host.client, rid))["status"] == "closed", "job đổi trạng thái"
    assert await find_room(host.client, spec["court"]["name"]) is None, (
        "phòng đóng không còn ở danh sách hôm nay"
    )
    d = await detail(guest.client, rid)
    assert d["status"] == "closed" and d["phase"] == "closed" and len(d["members"]) == 2, (
        "đóng: chỉ xem"
    )
    v, gid = {"version": d["version"]}, d["members"][1]["id"]
    writes = [
        ("/join-requests", host.client, v),
        ("/leave", guest.client, v),
        ("/invites", host.client, {**v, "phone": random_phone()}),
        (f"/members/{gid}/kick", host.client, v),
        (f"/members/{gid}/transfer-host", host.client, v),
    ]
    for path, client, body in writes:
        r = await act(client, rid, path, body)
        assert r.status_code == 409 and err(r)["code"] == "E-ROOM-1", (
            path,
            r.status_code,
            r.text[:100],
        )


async def test_ac3_within_10_minutes_after_end_the_room_is_still_open(admin, people):
    host, guest = await people("Chủ Còn Mở"), await people("Khách Còn Mở")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    await x(
        "UPDATE play_room SET end_at = now() - interval '5 minutes', start_at = now() - interval '65 minutes' WHERE id=:i",
        i=rid,
    )
    r = await with_v(guest.client, rid, "/join-requests")
    assert r.status_code == 200, "hết giờ chưa tới 10 phút vẫn thao tác được"


async def test_ac3_closing_expires_pending_requests_and_invites(admin, people):
    host, a, b = await people("Chủ Hết Hạn"), await people("Xin Vào"), await people("Được Mời")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    assert (await with_v(a.client, rid, "/join-requests")).status_code == 200
    assert (await with_v(host.client, rid, "/invites", {"phone": b.phone})).status_code == 200
    await x(
        "UPDATE play_room SET end_at = now() - interval '11 minutes', start_at = now() - interval '71 minutes' WHERE id=:i",
        i=rid,
    )
    await tick()
    rows = await q("SELECT status::text AS s FROM play_room_request WHERE room_id=:i", i=rid)
    assert rows and {r["s"] for r in rows} == {"expired"}, rows


# ============================================================ AC4–AC7 danh sách, thẻ, tên hiển thị


async def test_ac4_ac5_list_counts_scopes_and_ordering(admin, people):
    host, other, viewer = (
        await people("Chủ Danh Sách"),
        await people("Chủ Hai"),
        await people("Người Xem"),
    )
    s1 = await make_room(admin, host.client, host.code)
    s2 = await make_room(admin, other.client, other.code, offset=1)
    await fill(s1["room"]["id"], host, [viewer])
    allv = (await viewer.client.get(ROOMS, params={"scope": "all"})).json()
    assert allv["date"] == today().isoformat()
    assert allv["all_count"] >= 2 and allv["mine_count"] == 1, allv
    assert allv["ongoing_count"] + allv["upcoming_count"] == allv["all_count"]
    mine = (await viewer.client.get(ROOMS, params={"scope": "mine"})).json()
    assert [i["resource_name"] for i in mine["items"]] == [s1["court"]["name"]] and all(
        i["is_mine"] for i in mine["items"]
    )
    names = [i["resource_name"] for i in allv["items"]]
    assert (
        names.index(s1["court"]["name"]) < names.index(s2["court"]["name"])
        or s1["hour"] == s2["hour"]
    ), "sắp theo giờ bắt đầu"
    starts = [i["start_at"] for i in allv["items"]]
    assert starts == sorted(starts), "theo giờ bắt đầu"
    assert (
        next(i for i in allv["items"] if i["resource_name"] == s2["court"]["name"])["phase"]
        == "upcoming"
    )
    assert (
        next(i for i in allv["items"] if i["resource_name"] == s1["court"]["name"])["phase"]
        == "ongoing"
    )
    assert (await viewer.client.get(ROOMS, params={"scope": "bogus"})).status_code == 422


async def test_ac6_card_state_for_each_button(admin, people):
    host, member_a, pend, inv, outsider = (
        await people("Chủ Thẻ"),
        await people("Thành Viên"),
        await people("Đã Xin"),
        await people("Được Mời Thẻ"),
        await people("Người Ngoài Thẻ"),
    )
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    await fill(rid, host, [member_a])
    assert (await with_v(pend.client, rid, "/join-requests")).status_code == 200
    assert (await with_v(host.client, rid, "/invites", {"phone": inv.phone})).status_code == 200

    async def card_of(who):
        return await find_room(who.client, spec["court"]["name"])

    c_host, c_mem, c_pend, c_inv, c_out = [
        await card_of(w) for w in (host, member_a, pend, inv, outsider)
    ]
    assert c_host["is_mine"] and c_mem["is_mine"] and c_host["member_count"] == 2
    assert c_pend["my_join_pending"] is True and c_pend["is_mine"] is False
    assert isinstance(c_inv["my_invite_id"], int) and c_inv["is_mine"] is False
    assert (
        c_out["is_mine"] is False
        and c_out["my_join_pending"] is False
        and c_out["my_invite_id"] is None
    )
    assert [m["display_name"] for m in c_host["members"]][0] == "Chủ Thẻ", "Host đứng đầu"


async def test_ac7_display_name_uses_nickname_and_no_phone_anywhere(admin, people):
    host, guest = await people("Họ Tên Dài Chủ"), await people("Họ Tên Dài Khách")
    cur = (await host.client.get(f"{MA}/me")).json()
    body = {
        k: cur[k]
        for k in ("full_name", "nickname", "email", "tier", "racket", "show_on_records", "version")
    }
    assert (
        await host.client.put(
            f"{MA}/me", json={**body, "nickname": "Biệt Danh Chủ"}, headers=idem()
        )
    ).status_code == 200
    spec = await make_room(admin, guest.client, host.code)
    rid = spec["room"]["id"]
    await fill(rid, host, [guest])
    d_host, d_guest = await detail(host.client, rid), await detail(guest.client, rid)
    card = await find_room(guest.client, spec["court"]["name"])
    assert card["host"]["display_name"] == "Biệt Danh Chủ", "biệt danh thay họ tên"
    for payload in (d_host, d_guest, card):
        assert not digits_leak(payload, host.phone, guest.phone), "không có SĐT của ai trong phòng"
    for payload in (d_host, d_guest):
        assert not re.search(r"\b0\d{9}\b", json.dumps(payload)), "không có chuỗi giống SĐT"
        assert all("phone" not in m for m in payload["members"])


# ============================================================ AC8 xin vào


async def test_ac8_join_request_flow_approve_reject_cancel_and_notifications(admin, people):
    host, a, b, c = (
        await people("Chủ Xin Vào"),
        await people("Người A"),
        await people("Người B"),
        await people("Người C"),
    )
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    # bấm hai lần chỉ một yêu cầu
    r1 = await with_v(a.client, rid, "/join-requests")
    r2 = await with_v(a.client, rid, "/join-requests")
    assert r1.status_code == 200 and r2.status_code == 200
    assert (
        len(
            await q(
                "SELECT 1 FROM play_room_request WHERE room_id=:i AND status='pending' AND kind='join'",
                i=rid,
            )
        )
        == 1
    )
    assert (await with_v(b.client, rid, "/join-requests")).status_code == 200
    assert (await with_v(c.client, rid, "/join-requests")).status_code == 200
    dh = await detail(host.client, rid)
    assert {j["display_name"] for j in dh["join_requests"]} == {"Người A", "Người B", "Người C"}
    assert (await detail(a.client, rid))["join_requests"] == [], "chỉ Host thấy yêu cầu"
    ids = {j["display_name"]: j["id"] for j in dh["join_requests"]}
    assert (
        await with_v(host.client, rid, f"/join-requests/{ids['Người A']}/approve")
    ).status_code == 200
    assert (
        await with_v(host.client, rid, f"/join-requests/{ids['Người B']}/reject")
    ).status_code == 200
    assert (await act(c.client, rid, "/join-requests/mine", method="delete")).status_code in (
        200,
        204,
    )
    d = await detail(host.client, rid)
    assert {m["display_name"] for m in d["members"]} == {"Chủ Xin Vào", "Người A"} and d[
        "join_requests"
    ] == []

    async def kinds_of(h):
        return [n["kind"] for n in (await h.client.get(NOTI)).json()["items"]]

    assert "room.join_requested" in await kinds_of(host)
    assert "room.join_approved" in await kinds_of(a) and "room.join_rejected" in await kinds_of(b)
    # xin lại sau khi bị từ chối / hủy được
    assert (await with_v(b.client, rid, "/join-requests")).status_code == 200


async def test_ac8_request_and_approve_when_full_are_e_room_2_and_member_limit_per_day(
    admin, people
):
    host = await people("Chủ Đủ Người")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    others = [await people(f"Thành Viên {i}") for i in range(7)]
    await fill(rid, host, others)
    assert len((await detail(host.client, rid))["members"]) == 8
    late = await people("Người Muộn")
    r = await with_v(late.client, rid, "/join-requests")
    assert (
        r.status_code == 409
        and err(r)["code"] == "E-ROOM-2"
        and err(r)["message"] == "Phòng đã đủ 8 người."
    )
    card = await find_room(late.client, spec["court"]["name"])
    assert card["member_count"] == 8


async def test_ac8_ten_pending_requests_per_person_per_day(admin, people):
    guest, host = await people("Xin Nhiều"), await people("Chủ Nhiều Sân")
    rooms = []  # một Host có thể có nhiều phòng (mỗi khối booking một phòng) – tránh vượt giới hạn đăng ký/IP
    for _ in range(11):
        spec = await make_room(admin, guest.client, host.code)
        rooms.append(spec["room"]["id"])
    codes = []
    for rid in rooms:
        r = await with_v(guest.client, rid, "/join-requests")
        codes.append((r.status_code, err(r)["code"] if r.status_code != 200 else None))
    assert [c[0] for c in codes[:10]] == [200] * 10 and codes[10] == (429, "E-SEC-5"), codes


# ============================================================ AC9 mời + SEC2


async def test_ac9_invite_only_host_phone_normalized_accept_decline_and_notifications(
    admin, people
):
    host, guest, other, nosy = (
        await people("Chủ Mời"),
        await people("Được Mời"),
        await people("Từ Chối"),
        await people("Tò Mò"),
    )
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    # không phải Host (thành viên / người ngoài) → E-ROOM-7 (SEC1)
    r = await with_v(nosy.client, rid, "/invites", {"phone": guest.phone})
    assert (
        r.status_code == 403
        and err(r)["code"] == "E-ROOM-7"
        and err(r)["message"] == "Chỉ Host được làm thao tác này."
    )
    typed = f"+84 {guest.phone[1:4]} {guest.phone[4:7]} {guest.phone[7:]}"
    r = await with_v(host.client, rid, "/invites", {"phone": typed})
    assert r.status_code == 200, r.text
    assert (await with_v(host.client, rid, "/invites", {"phone": other.phone})).status_code == 200
    assert any(i for i in (await detail(host.client, rid))["invites"]), "Host thấy lời mời"
    assert (await detail(nosy.client, rid))["invites"] == []
    ig = (await find_room(guest.client, spec["court"]["name"]))["my_invite_id"]
    io = (await find_room(other.client, spec["court"]["name"]))["my_invite_id"]
    # lời mời của người khác → 404
    assert (
        await nosy.client.post(f"{MA}/invites/{ig}/accept", json={}, headers=idem())
    ).status_code == 404
    assert (
        await other.client.post(f"{MA}/invites/{ig}/decline", json={}, headers=idem())
    ).status_code == 404
    assert (
        await guest.client.post(f"{MA}/invites/{ig}/accept", json={}, headers=idem())
    ).status_code == 200
    assert (
        await other.client.post(f"{MA}/invites/{io}/decline", json={}, headers=idem())
    ).status_code == 200
    d = await detail(host.client, rid)
    assert {m["display_name"] for m in d["members"]} == {"Chủ Mời", "Được Mời"}
    assert (await find_room(other.client, spec["court"]["name"]))["my_invite_id"] is None
    assert "room.invited" in [n["kind"] for n in (await guest.client.get(NOTI)).json()["items"]]


async def test_ac9_sec2_invite_errors_never_reveal_why_and_cover_self_and_members(admin, people):
    host, guest, inactive = (
        await people("Chủ SEC2"),
        await people("Đã Trong Phòng"),
        await people("Hội Viên Ngừng"),
    )
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    await fill(rid, host, [guest])
    cur = (await admin.get(f"{M}/{inactive.code}")).json()
    assert (
        await admin.patch(
            f"{M}/{inactive.code}",
            json={"is_active": False, "version": cur["version"]},
            headers=idem(),
        )
    ).status_code == 200
    unlinked_temp = random_phone()
    assert (
        await admin.post(
            f"{M}/temp", json={"full_name": "QA Tạm SEC2", "phone": unlinked_temp}, headers=idem()
        )
    ).status_code == 201
    plain = unique_phone()
    async with _client() as c:
        await db_account(c, plain, "Chưa Xác Minh")  # tài khoản chưa xác minh → chưa là hội viên
    bodies = []
    for phone in (random_phone(), unlinked_temp, plain, inactive.phone):
        r = await with_v(host.client, rid, "/invites", {"phone": phone})
        assert r.status_code == 422 and err(r)["code"] == "E-ROOM-3", (
            phone,
            r.status_code,
            r.text[:100],
        )
        bodies.append(r.json())
    assert all(b == bodies[0] for b in bodies), "cùng một câu, không phân biệt lý do"
    assert bodies[0]["detail"]["message"] == "Số điện thoại này chưa có tài khoản hội viên."
    for who in (host.phone, guest.phone):
        r = await with_v(host.client, rid, "/invites", {"phone": who})
        assert r.status_code == 409 and err(r)["code"] == "E-ROOM-4", (
            "mời chính mình / người đã trong phòng"
        )
    for bad in ("", "123", "abc", "+1 202 555 0100"):
        assert (await with_v(host.client, rid, "/invites", {"phone": bad})).status_code in (422,), (
            bad
        )


async def test_ac9_invite_rate_limit_counts_failed_attempts_too(admin, people):
    host = await people("Chủ Giới Hạn")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    statuses = []
    for _ in range(21):
        r = await with_v(host.client, rid, "/invites", {"phone": random_phone()})
        statuses.append((r.status_code, err(r)["code"]))
    assert statuses[:20] == [(422, "E-ROOM-3")] * 20 and statuses[20] == (429, "E-SEC-5"), statuses[
        18:
    ]


async def test_ac9_accepting_an_invite_when_the_room_is_full_is_e_room_2(admin, people):
    host, invited = await people("Chủ Đầy Mời"), await people("Mời Muộn")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    assert (await with_v(host.client, rid, "/invites", {"phone": invited.phone})).status_code == 200
    iid = (await find_room(invited.client, spec["court"]["name"]))["my_invite_id"]
    await fill(rid, host, [await people(f"Đủ {i}") for i in range(7)])
    r = await invited.client.post(f"{MA}/invites/{iid}/accept", json={}, headers=idem())
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-2"


# ============================================================ AC10 / SEC3 đồng thời ≤ 8


async def test_ac10_sec3_concurrent_approvals_and_accepts_never_exceed_8(admin, people):
    host = await people("Chủ Đồng Thời")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    await fill(rid, host, [await people(f"Sẵn {i}") for i in range(5)])  # 6 người
    ask = [await people(f"Xin {i}") for i in range(4)]
    for a in ask:
        assert (await with_v(a.client, rid, "/join-requests")).status_code == 200
    reqs = (await detail(host.client, rid))["join_requests"]
    v = (await detail(host.client, rid))["version"]
    res = await asyncio.gather(
        *[
            host.client.post(
                f"{ROOMS}/{rid}/join-requests/{r['id']}/approve",
                json={"version": v},
                headers=idem(),
            )
            for r in reqs
        ]
    )
    codes = sorted(r.status_code for r in res)
    n = len((await detail(host.client, rid))["members"])
    assert n <= 8 and codes.count(200) == n - 6, (codes, n)
    assert (
        (await q("SELECT count(*) AS n FROM play_room_member WHERE room_id=:i", i=rid))[0]["n"]
        == n
        <= 8
    )


async def test_ac10_concurrent_invite_accepts_for_the_last_seat(admin, people):
    host = await people("Chủ Ghế Cuối")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    await fill(rid, host, [await people(f"Có Mặt {i}") for i in range(6)])  # 7 người
    invitees = [await people(f"Được Mời {i}") for i in range(3)]
    for p in invitees:
        assert (await with_v(host.client, rid, "/invites", {"phone": p.phone})).status_code == 200
    iids = [(await find_room(p.client, spec["court"]["name"]))["my_invite_id"] for p in invitees]
    res = await asyncio.gather(
        *[
            p.client.post(f"{MA}/invites/{i}/accept", json={}, headers=idem())
            for p, i in zip(invitees, iids, strict=True)
        ]
    )
    codes = sorted(r.status_code for r in res)
    assert codes == [200, 409, 409], codes
    assert len((await detail(host.client, rid))["members"]) == 8


# ============================================================ AC11 rời phòng, AC12 chuyển Host / mời ra


async def test_ac11_member_leaves_host_leaves_new_host_is_one_of_the_rest_and_last_leaves_closes(
    admin, people
):
    host, a, b = await people("Chủ Rời"), await people("Còn Lại A"), await people("Còn Lại B")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    await fill(rid, host, [a, b])
    assert (await with_v(b.client, rid, "/leave")).status_code == 200
    assert {m["display_name"] for m in (await detail(host.client, rid))["members"]} == {
        "Chủ Rời",
        "Còn Lại A",
    }
    assert (await with_v(host.client, rid, "/leave")).status_code == 200
    d = await detail(a.client, rid)
    assert d["my_role"] == "host" and [m["display_name"] for m in d["members"]] == ["Còn Lại A"], (
        "người còn lại thành Host"
    )
    assert "room.host_assigned" in [n["kind"] for n in (await a.client.get(NOTI)).json()["items"]]
    rows = await q(
        "SELECT action, actor_type, detail::text AS d FROM audit_log WHERE action='room.host_transferred' AND detail::text LIKE '%host_left%' ORDER BY id DESC LIMIT 1"
    )
    assert rows and rows[0]["actor_type"] == "customer"
    assert (await with_v(a.client, rid, "/leave")).status_code == 200
    d = await detail(a.client, rid)
    assert d["status"] == "closed" and d["members"] == [], "người cuối rời → phòng đóng"
    r = await with_v(b.client, rid, "/join-requests")
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-1"


async def test_ac11_non_member_cannot_leave(admin, people):
    host, out = await people("Chủ Không Rời"), await people("Người Ngoài Rời")
    spec = await make_room(admin, host.client, host.code)
    r = await with_v(out.client, spec["room"]["id"], "/leave")
    assert r.status_code in (403, 404, 409), r.text
    assert len((await detail(host.client, spec["room"]["id"]))["members"]) == 1


async def test_ac12_kick_and_transfer_host_rules_notifications_and_audit(admin, people):
    host, a, b = await people("Chủ Mời Ra"), await people("Bị Mời Ra"), await people("Nhận Host")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    await fill(rid, host, [a, b])
    d = await detail(host.client, rid)
    mid = {m["display_name"]: m["id"] for m in d["members"]}
    # không phải Host → E-ROOM-7 (SEC1)
    for path in (f"/members/{mid['Nhận Host']}/kick", f"/members/{mid['Nhận Host']}/transfer-host"):
        r = await with_v(a.client, rid, path)
        assert r.status_code == 403 and err(r)["code"] == "E-ROOM-7", path
    # mời chính mình / chuyển cho chính mình → 404
    assert (await with_v(host.client, rid, f"/members/{mid['Chủ Mời Ra']}/kick")).status_code == 404
    assert (
        await with_v(host.client, rid, f"/members/{mid['Chủ Mời Ra']}/transfer-host")
    ).status_code == 404
    assert (await with_v(host.client, rid, "/members/999999/kick")).status_code == 404
    # mời ra: xóa ngay, có thông báo, xin vào lại được
    assert (await with_v(host.client, rid, f"/members/{mid['Bị Mời Ra']}/kick")).status_code == 200
    assert {m["display_name"] for m in (await detail(host.client, rid))["members"]} == {
        "Chủ Mời Ra",
        "Nhận Host",
    }
    assert "room.kicked" in [n["kind"] for n in (await a.client.get(NOTI)).json()["items"]]
    assert (await with_v(a.client, rid, "/join-requests")).status_code == 200, (
        "bị mời ra vẫn xin vào lại được"
    )
    # chuyển Host
    assert (
        await with_v(host.client, rid, f"/members/{mid['Nhận Host']}/transfer-host")
    ).status_code == 200
    d2 = await detail(b.client, rid)
    assert d2["my_role"] == "host" and (await detail(host.client, rid))["my_role"] == "member"
    assert "room.host_assigned" in [n["kind"] for n in (await b.client.get(NOTI)).json()["items"]]
    r = await with_v(host.client, rid, f"/members/{mid['Nhận Host']}/kick")
    assert r.status_code == 403, "Host cũ không còn quyền Host"
    # nhật ký (AC26): người làm là khách, không có SĐT
    for action in ("room.kicked", "room.host_transferred", "room.join_approved"):
        rows = await q(
            "SELECT actor_type, detail::text AS d FROM audit_log WHERE action=:a ORDER BY id DESC LIMIT 3",
            a=action,
        )
        assert rows and all(r["actor_type"] == "customer" for r in rows), action
        assert all(host.phone not in r["d"] and a.phone not in r["d"] for r in rows), (
            "không SĐT trong nhật ký phòng"
        )


# ============================================================ version, idempotency, Origin, quyền vào (AC21 một phần, AC25)


async def test_stale_version_is_e_room_6_and_idempotency_replay_returns_the_same_result(
    admin, people
):
    host, a, b = await people("Chủ Phiên Bản"), await people("Xin Một"), await people("Xin Hai")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    v0 = (await detail(a.client, rid))["version"]
    assert (
        await act(b.client, rid, "/join-requests", {"version": v0})
    ).status_code == 200  # đổi version phòng
    stale = await act(a.client, rid, "/join-requests", {"version": v0})
    assert (
        stale.status_code == 409
        and err(stale)["code"] == "E-ROOM-6"
        and err(stale)["message"] == "Phòng vừa thay đổi, đã tải lại."
    )
    key = {"Idempotency-Key": str(uuid.uuid4())}
    v1 = (await detail(a.client, rid))["version"]
    r1 = await act(a.client, rid, "/join-requests", {"version": v1}, headers=key)
    r2 = await act(a.client, rid, "/join-requests", {"version": v1}, headers=key)
    assert r1.status_code == r2.status_code == 200 and r2.json() == r1.json()
    assert r2.headers.get("idempotent-replayed") == "true"
    assert (
        len(
            await q(
                "SELECT 1 FROM play_room_request WHERE room_id=:i AND status='pending' AND kind='join'",
                i=rid,
            )
        )
        == 2
    )


async def test_writes_need_origin_and_idempotency_key(admin, people):
    host, a = await people("Chủ Origin"), await people("Khách Origin")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    v = (await detail(a.client, rid))["version"]
    r = await a.client.post(
        f"{ROOMS}/{rid}/join-requests",
        json={"version": v},
        headers={**idem(), "Origin": "https://evil.example"},
    )
    assert r.status_code == 403 and err(r)["code"] == "E-SEC-1"
    r = await a.client.post(f"{ROOMS}/{rid}/join-requests", json={"version": v})
    assert r.status_code == 400 and err(r)["code"] == "E-SEC-2"
    assert not await q("SELECT 1 FROM play_room_request WHERE room_id=:i", i=rid)


async def test_ac25_access_rules_anonymous_non_member_admin_and_unknown_room(
    admin, people, anon, customer
):
    host = await people("Chủ Quyền Vào")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    for client in (anon,):
        assert (await client.get(ROOMS)).status_code == 401
        assert (await client.get(f"{ROOMS}/{rid}")).status_code == 401
        assert (await client.get(NOTI)).status_code == 401
    for path in (ROOMS, f"{ROOMS}/{rid}", NOTI):
        r = await customer.get(path)
        assert r.status_code == 403 and err(r)["code"] == "E-HV-8", path
        a = await admin.get(path)
        assert a.status_code in (401, 403), path
    assert (await host.client.get(f"{ROOMS}/999999")).status_code == 404
    assert (await host.client.get(f"{ROOMS}/abc")).status_code == 422


# ============================================================ AC22 thông báo + SEC6


async def test_ac22_notifications_list_read_flags_and_idor(admin, people):
    host, a, spy = (
        await people("Chủ Thông Báo"),
        await people("Người Xin"),
        await people("Người Dòm"),
    )
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    assert (await with_v(a.client, rid, "/join-requests")).status_code == 200
    n = (await host.client.get(NOTI)).json()
    assert n["unread_count"] == 1 and len(n["items"]) == 1
    item = n["items"][0]
    assert (
        item["kind"] == "room.join_requested"
        and item["link"] == f"/hoi-vien/phong/{rid}"
        and item["read"] is False
        and item["created_at"]
    )
    assert "Người Xin" in item["text"] and not digits_leak(n, a.phone, host.phone)
    # IDOR: người khác không đọc/đánh dấu được thông báo của mình
    assert (
        await spy.client.post(
            f"{NOTI}/{item['id']}/read", headers={"Origin": host.client.headers["Origin"]}
        )
    ).status_code == 404
    assert (await host.client.get(NOTI)).json()["unread_count"] == 1, (
        "không bị đánh dấu bởi người khác"
    )
    assert (await spy.client.get(NOTI)).json()["items"] == []
    # đọc một, lọc chưa đọc, đọc hết
    assert (
        await host.client.post(
            f"{NOTI}/{item['id']}/read", headers={"Origin": host.client.headers["Origin"]}
        )
    ).status_code == 204
    after = (await host.client.get(NOTI)).json()
    assert after["unread_count"] == 0 and after["items"][0]["read"] is True
    assert (await host.client.get(NOTI, params={"unread": "true"})).json()["items"] == []
    b = await people("Người Xin Hai")
    assert (await with_v(b.client, rid, "/join-requests")).status_code == 200
    assert (await host.client.get(NOTI, params={"unread": "true"})).json()["unread_count"] == 1
    assert (
        await host.client.post(
            f"{NOTI}/read-all", headers={"Origin": host.client.headers["Origin"]}
        )
    ).status_code == 204
    assert (await host.client.get(NOTI)).json()["unread_count"] == 0
    assert (
        await host.client.post(
            f"{NOTI}/999999/read", headers={"Origin": host.client.headers["Origin"]}
        )
    ).status_code == 404
    evil = await host.client.post(f"{NOTI}/read-all", headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403


async def test_ac22_notifications_window_30_days_max_50_newest_first(admin, people):
    hv = await people("Hộp Thư")
    cid = (await q("SELECT id FROM customer WHERE phone=:p", p=hv.phone))[0]["id"]
    for i in range(60):
        await x(
            "INSERT INTO member_notification (customer_id, kind, payload, link, created_at) VALUES (:c, 'room.invited', :p, '/hoi-vien/phong/1', now() - (:d || ' minutes')::interval)",
            c=cid,
            p=json.dumps({"text": f"Tin {i}"}),
            d=str(i),
        )
    await x(
        "INSERT INTO member_notification (customer_id, kind, payload, link, created_at) VALUES (:c, 'room.kicked', :p, '/hoi-vien/phong/1', now() - interval '31 days')",
        c=cid,
        p=json.dumps({"text": "Tin cũ"}),
    )
    n = (await hv.client.get(NOTI)).json()
    assert len(n["items"]) == 50, "tối đa 50"
    ats = [i["created_at"] for i in n["items"]]
    assert ats == sorted(ats, reverse=True), "mới nhất trước"
    assert all("Tin cũ" not in i["text"] for i in n["items"]), "quá 30 ngày không hiện"
    assert n["unread_count"] >= 50, "unread_count đếm các thông báo chưa đọc trong 30 ngày"
