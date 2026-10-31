"""T-017 mốc 1: phòng chơi – tạo phòng, danh sách, xin vào / mời / duyệt / rời / mời ra, thông báo.

Mỗi test một sân riêng; hội viên có tài khoản liên kết tạo bằng đăng ký 2 bước (T-021).
"""

import asyncio
import json
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import delete, select, update

from app.core import events
from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.auth.models import User
from app.modules.booking_engine import api as engine
from app.modules.booking_engine.models import OutboxEvent as Outbox
from app.modules.member_inbox.models import MemberNotification
from app.modules.members.models import Customer
from app.modules.play_rooms import actions, lifecycle
from app.modules.play_rooms.models import PlayRoom, PlayRoomMember, PlayRoomRequest
from tests.conftest import API, _client, idem, new_registered, unique_phone
from tests.helpers_booking import book, member, new_court, safe_hour, temp

MA = f"{API}/member-area"
ROOMS = f"{MA}/rooms"
NOTI = f"{MA}/notifications"


@dataclass
class Hv:
    client: AsyncClient
    code: str
    phone: str
    customer_id: int


@pytest.fixture
async def people():
    """``await people("Tên")`` -> hội viên có tài khoản liên kết, đã đăng nhập. Dọn khi xong."""
    phones: list[str] = []
    async with AsyncExitStack() as stack:

        async def make(name: str = "Hội Viên") -> Hv:
            phone = unique_phone()
            phones.append(phone)
            client = await stack.enter_async_context(new_registered(phone, name))
            me = (await client.get(f"{MA}/me")).json()
            async with SessionLocal() as s:
                cid = await s.scalar(select(Customer.id).where(Customer.phone == phone))
            return Hv(client, me["member_code"], phone, cid)

        yield make
    async with SessionLocal() as s:
        await s.execute(delete(Customer).where(Customer.phone.in_(phones)))
        await s.execute(delete(User).where(User.phone.in_(phones)))
        await s.commit()


async def room_for(staff, admin, host_code: str | None, customer: dict | None = None) -> dict:
    """Đặt quầy giờ đang diễn ra trên sân mới -> chạy handler tạo phòng -> trả thông tin phòng."""
    court = await new_court(admin)
    hour = await safe_hour()
    r = await book(staff, court["code"], hour, hour + 1, customer or member(host_code))
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    async with SessionLocal() as s:
        await lifecycle.ensure_for_codes(s, [code])
        await s.commit()
        room = await s.scalar(select(PlayRoom).where(PlayRoom.booking_code == code))
    return {"code": code, "court": court, "room": room}


async def detail(client, room_id: int):
    r = await client.get(f"{ROOMS}/{room_id}")
    assert r.status_code == 200, r.text
    return r.json()


async def post(client, path: str, body: dict | None = None):
    return await client.post(f"{ROOMS}{path}", json=body or {}, headers=idem())


async def version(client, room_id: int) -> int:
    return (await detail(client, room_id))["version"]


async def notifications(client) -> dict:
    r = await client.get(NOTI)
    assert r.status_code == 200, r.text
    return r.json()


def code_of(r) -> str:
    return r.json()["detail"]["code"]


# ------------------------------------------------------------------ AC1, AC2: tạo phòng


async def test_booking_creates_room_with_host(staff, admin, people):
    host = await people("Trần Văn Host")
    info = await room_for(staff, admin, host.code)
    room = info["room"]
    assert room is not None and room.host_customer_id == host.customer_id
    assert room.resource_code == info["court"]["code"] and room.status == "open"
    async with SessionLocal() as s:
        rows = list(
            await s.scalars(select(PlayRoomMember).where(PlayRoomMember.room_id == room.id))
        )
    assert [(m.customer_id, m.queue_state) for m in rows] == [(host.customer_id, "waiting")]

    # Tạo lại (sự kiện lặp / job bù) không sinh phòng thứ hai
    async with SessionLocal() as s:
        assert await lifecycle.ensure_for_codes(s, [info["code"]]) == 0
        await s.commit()

    d = await detail(host.client, room.id)
    assert d["my_role"] == "host" and d["members"][0]["role"] == "host"
    assert d["members"][0]["display_name"] == "Trần Văn Host"
    assert d["closes_at"] > d["end_at"] and d["current_match"] is None


async def test_booking_event_carries_court_and_time_but_no_customer(staff, admin, people):
    host = await people()
    court = await new_court(admin)
    hour = await safe_hour()
    r = await book(staff, court["code"], hour, hour + 1, member(host.code))
    code = r.json()["code"]
    async with SessionLocal() as s:
        row = await s.scalar(
            select(Outbox).where(
                Outbox.event_type == "booking.created", Outbox.payload["code"].astext == code
            )
        )
    payload = row.payload
    assert payload["resource_code"] == court["code"] and payload["resource_name"] == court["name"]
    assert payload["resource_type_name"] and payload["start_at"] < payload["end_at"]
    assert "customer_ref" not in payload and host.phone not in json.dumps(payload)

    # Handler sự kiện (worker) tạo phòng
    await events.publish(events.BOOKING_CREATED, payload)
    async with SessionLocal() as s:
        assert await s.scalar(select(PlayRoom.id).where(PlayRoom.booking_code == code))


async def test_walk_in_without_profile_gets_no_room():
    src = engine.RoomSource(
        code="BK-20991231-001-01",
        customer_ref="phone:0912345678",
        resource_code="S1",
        resource_name="Sân 1",
        resource_type_name="Thường",
        start_at=datetime.now(UTC),
        end_at=datetime.now(UTC) + timedelta(hours=1),
    )
    async with SessionLocal() as s:
        assert await lifecycle.ensure_rooms(s, [src]) == 0
        await s.rollback()


async def test_room_hidden_until_host_is_linked_member(staff, admin, people):
    """Hồ sơ tạm / hội viên chưa có tài khoản -> phòng có nhưng ẩn (404); liên kết rồi thì hiện."""
    viewer = await people()
    phone = unique_phone()
    info = await room_for(staff, admin, None, temp("Khách Tạm Phòng", phone))
    room = info["room"]
    assert room is not None  # booking có hồ sơ tạm -> có phòng (chưa hiện)
    assert (await viewer.client.get(f"{ROOMS}/{room.id}")).status_code == 404
    listed = (await viewer.client.get(ROOMS)).json()
    assert room.id not in [c["id"] for c in listed["items"]]
    r = await post(viewer.client, f"/{room.id}/join-requests", {"version": room.version})
    assert r.status_code == 404

    # Khách đăng ký + xác minh SĐT -> hồ sơ tạm nâng lên hội viên (T-021), cùng id -> phòng hiện
    try:
        async with new_registered(phone, "Khách Tạm Phòng"):
            pass
        assert (await viewer.client.get(f"{ROOMS}/{room.id}")).status_code == 200
    finally:
        async with SessionLocal() as s:
            await s.execute(delete(Customer).where(Customer.phone == phone))
            await s.execute(delete(User).where(User.phone == phone))
            await s.commit()


async def test_inactive_host_hides_room(staff, admin, people):
    host, viewer = await people(), await people()
    room = (await room_for(staff, admin, host.code))["room"]
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == host.customer_id).values(is_active=False)
        )
        await s.commit()
    assert (await viewer.client.get(f"{ROOMS}/{room.id}")).status_code == 404


# ------------------------------------------------------------------ AC4–AC7: danh sách sân


async def test_room_list_counts_and_cards(staff, admin, people):
    host, other = await people("Nguyễn Host"), await people("Lê Khách")
    room = (await room_for(staff, admin, host.code))["room"]

    r = await host.client.get(ROOMS)
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache, private"
    body = r.json()
    card = next(c for c in body["items"] if c["id"] == room.id)
    assert card["phase"] == "ongoing" and card["is_mine"] is True
    assert card["host"]["display_name"] == "Nguyễn Host"
    assert (card["member_count"], card["capacity"]) == (1, 8)
    assert body["mine_count"] >= 1 and body["all_count"] >= body["mine_count"]
    assert body["ongoing_count"] + body["upcoming_count"] == body["all_count"]
    mine = (await host.client.get(ROOMS, params={"scope": "mine"})).json()
    assert room.id in [c["id"] for c in mine["items"]]

    other_view = (await other.client.get(ROOMS)).json()
    card = next(c for c in other_view["items"] if c["id"] == room.id)
    assert card["is_mine"] is False and card["my_join_pending"] is False
    assert room.id not in [
        c["id"] for c in (await other.client.get(ROOMS, params={"scope": "mine"})).json()["items"]
    ]
    # Không lộ SĐT ở đâu cả (AC7, SEC2)
    for text in (
        json.dumps(body),
        json.dumps(other_view),
        json.dumps(await detail(other.client, room.id)),
    ):
        assert host.phone not in text and other.phone not in text


async def test_rooms_need_member_session(anon, customer):
    assert (await anon.get(ROOMS)).status_code == 401
    r = await customer.get(ROOMS)  # tài khoản chưa xác minh SĐT -> chưa là hội viên
    assert r.status_code == 403 and code_of(r) == "E-HV-8"


async def test_nickname_is_display_name(staff, admin, people):
    host = await people("Phạm Văn Dài")
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == host.customer_id).values(nickname="Dài Smash")
        )
        await s.commit()
    room = (await room_for(staff, admin, host.code))["room"]
    assert (await detail(host.client, room.id))["members"][0]["display_name"] == "Dài Smash"


# ------------------------------------------------------------------ AC8: xin vào, duyệt


async def test_join_request_approve_flow(staff, admin, people):
    host, guest = await people("Host A"), await people("Khách B")
    room = (await room_for(staff, admin, host.code))["room"]
    v = await version(guest.client, room.id)

    r = await post(guest.client, f"/{room.id}/join-requests", {"version": v})
    assert r.status_code == 200, r.text
    assert (
        r.json()["my_join_pending"] is True and r.json()["join_requests"] == []
    )  # không phải Host
    again = await post(guest.client, f"/{room.id}/join-requests", {"version": r.json()["version"]})
    assert again.status_code == 200  # bấm lại không tạo thêm
    async with SessionLocal() as s:
        pending = list(
            await s.scalars(select(PlayRoomRequest).where(PlayRoomRequest.room_id == room.id))
        )
    assert len(pending) == 1

    # Host thấy yêu cầu + có thông báo
    d = await detail(host.client, room.id)
    [req] = d["join_requests"]
    assert req["display_name"] == "Khách B"
    n = await notifications(host.client)
    assert n["unread_count"] >= 1
    item = next(i for i in n["items"] if i["kind"] == "room.join_requested")
    assert "Khách B" in item["text"] and item["link"] == f"/hoi-vien/phong/{room.id}"

    # Khách không duyệt được (SEC1)
    r = await post(
        guest.client, f"/{room.id}/join-requests/{req['id']}/approve", {"version": d["version"]}
    )
    assert r.status_code == 403 and code_of(r) == "E-ROOM-7"
    # version cũ -> E-ROOM-6
    r = await post(host.client, f"/{room.id}/join-requests/{req['id']}/approve", {"version": v})
    assert r.status_code == 409 and code_of(r) == "E-ROOM-6"

    r = await post(
        host.client, f"/{room.id}/join-requests/{req['id']}/approve", {"version": d["version"]}
    )
    assert r.status_code == 200, r.text
    assert [m["display_name"] for m in r.json()["members"]] == ["Host A", "Khách B"]
    assert r.json()["members"][1]["queue_state"] == "waiting"
    g = await detail(guest.client, room.id)
    assert g["my_role"] == "member" and g["my_join_pending"] is False
    assert any(
        i["kind"] == "room.join_approved" for i in (await notifications(guest.client))["items"]
    )
    async with SessionLocal() as s:
        row = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "room.join_approved", AuditLog.entity_code == str(room.id)
            )
        )
    assert row is not None and row.actor_type == "customer"
    assert guest.phone not in json.dumps(row.detail)

    # Đã trong phòng -> xin nữa là E-ROOM-4
    r = await post(guest.client, f"/{room.id}/join-requests", {"version": g["version"]})
    assert r.status_code == 409 and code_of(r) == "E-ROOM-4"


async def test_reject_and_cancel_join(staff, admin, people):
    host, guest = await people(), await people()
    room = (await room_for(staff, admin, host.code))["room"]
    r = await post(guest.client, f"/{room.id}/join-requests", {"version": room.version})
    r = await guest.client.delete(f"{ROOMS}/{room.id}/join-requests/mine", headers=idem())
    assert r.status_code == 200 and r.json()["my_join_pending"] is False
    assert (await detail(host.client, room.id))["join_requests"] == []

    r = await post(guest.client, f"/{room.id}/join-requests", {"version": r.json()["version"]})
    d = await detail(host.client, room.id)
    rid = d["join_requests"][0]["id"]
    r = await post(host.client, f"/{room.id}/join-requests/{rid}/reject", {"version": d["version"]})
    assert r.status_code == 200 and len(r.json()["members"]) == 1
    assert any(
        i["kind"] == "room.join_rejected" for i in (await notifications(guest.client))["items"]
    )
    # Yêu cầu đã xử lý -> duyệt lại là E-ROOM-6
    r = await post(
        host.client, f"/{room.id}/join-requests/{rid}/approve", {"version": r.json()["version"]}
    )
    assert r.status_code == 409 and code_of(r) == "E-ROOM-6"


async def test_join_requests_limited_per_day(staff, admin, people, monkeypatch):
    monkeypatch.setattr(actions, "JOIN_PER_DAY", 1)
    host, guest = await people(), await people()
    r1 = (await room_for(staff, admin, host.code))["room"]
    r2 = (await room_for(staff, admin, host.code))["room"]
    assert (
        await post(guest.client, f"/{r1.id}/join-requests", {"version": r1.version})
    ).status_code == 200
    r = await post(guest.client, f"/{r2.id}/join-requests", {"version": r2.version})
    assert r.status_code == 429 and code_of(r) == "E-SEC-5"


# ------------------------------------------------------------------ AC9: mời bằng SĐT


async def test_invite_by_phone(staff, admin, people):
    host, friend, stranger = await people("Host M"), await people("Bạn Được Mời"), await people()
    room = (await room_for(staff, admin, host.code))["room"]
    v = room.version

    r = await post(host.client, f"/{room.id}/invites", {"phone": unique_phone(), "version": v})
    assert r.status_code == 422 and code_of(r) == "E-ROOM-3"
    msg = r.json()["detail"]["message"]
    # Hội viên chưa có tài khoản (HV0031 mẫu) -> cùng câu, không phân biệt (SEC2)
    async with SessionLocal() as s:
        no_account = await s.scalar(select(Customer.phone).where(Customer.member_code == "HV0031"))
    r = await post(host.client, f"/{room.id}/invites", {"phone": no_account, "version": v})
    assert r.status_code == 422 and r.json()["detail"]["message"] == msg
    assert set(r.json()["detail"]) == {"code", "message"}
    r = await post(host.client, f"/{room.id}/invites", {"phone": host.phone, "version": v})
    assert r.status_code == 409 and code_of(r) == "E-ROOM-4"
    r = await post(host.client, f"/{room.id}/invites", {"phone": "12345", "version": v})
    assert r.status_code == 422
    # Không phải Host -> E-ROOM-7
    r = await post(stranger.client, f"/{room.id}/invites", {"phone": friend.phone, "version": v})
    assert r.status_code == 403 and code_of(r) == "E-ROOM-7"

    spaced = f"+84 {friend.phone[1:4]} {friend.phone[4:7]} {friend.phone[7:]}"
    r = await post(host.client, f"/{room.id}/invites", {"phone": spaced, "version": v})
    assert r.status_code == 200, r.text
    assert [i["display_name"] for i in r.json()["invites"]] == ["Bạn Được Mời"]

    f = await detail(friend.client, room.id)
    assert f["my_role"] == "outsider" and f["my_invite_id"]
    card = next(c for c in (await friend.client.get(ROOMS)).json()["items"] if c["id"] == room.id)
    assert card["my_invite_id"] == f["my_invite_id"]
    noti = next(
        i for i in (await notifications(friend.client))["items"] if i["kind"] == "room.invited"
    )
    assert "Host M" in noti["text"] and friend.phone not in noti["text"]

    # Người khác không nhận lời thay được (404)
    r = await stranger.client.post(f"{MA}/invites/{f['my_invite_id']}/accept", headers=idem())
    assert r.status_code == 404
    r = await friend.client.post(f"{MA}/invites/{f['my_invite_id']}/accept", headers=idem())
    assert r.status_code == 200, r.text
    assert r.json()["my_role"] == "member" and r.json()["invites"] == []
    r = await friend.client.post(f"{MA}/invites/{f['my_invite_id']}/accept", headers=idem())
    assert r.status_code == 409 and code_of(r) == "E-ROOM-6"


async def test_decline_invite(staff, admin, people):
    host, friend = await people(), await people()
    room = (await room_for(staff, admin, host.code))["room"]
    await post(host.client, f"/{room.id}/invites", {"phone": friend.phone, "version": room.version})
    iid = (await detail(friend.client, room.id))["my_invite_id"]
    r = await friend.client.post(f"{MA}/invites/{iid}/decline", headers=idem())
    assert r.status_code == 200 and r.json()["my_role"] == "outsider"
    assert r.json()["my_invite_id"] is None


async def test_invites_rate_limited_counting_failures(staff, admin, people, monkeypatch):
    monkeypatch.setattr(actions, "INVITES_PER_HOUR", 2)
    host = await people()
    room = (await room_for(staff, admin, host.code))["room"]
    for _ in range(2):
        r = await post(
            host.client, f"/{room.id}/invites", {"phone": unique_phone(), "version": room.version}
        )
        assert code_of(r) == "E-ROOM-3"
    r = await post(
        host.client, f"/{room.id}/invites", {"phone": unique_phone(), "version": room.version}
    )
    assert r.status_code == 429 and code_of(r) == "E-SEC-5"


# ------------------------------------------------------------------ AC10: ≤ 8 người đồng thời


async def fill(room_id: int, count: int) -> None:
    """Thêm thành viên giả (id âm – không phải hồ sơ thật) cho tới ``count`` người."""
    async with SessionLocal() as s:
        have = len(
            list(await s.scalars(select(PlayRoomMember).where(PlayRoomMember.room_id == room_id)))
        )
        for i in range(count - have):
            s.add(PlayRoomMember(room_id=room_id, customer_id=-(room_id * 10 + have + i)))
        await s.commit()


async def test_full_room(staff, admin, people):
    host, guest, friend = await people(), await people(), await people()
    room = (await room_for(staff, admin, host.code))["room"]
    await post(guest.client, f"/{room.id}/join-requests", {"version": room.version})
    await fill(room.id, 8)
    d = await detail(host.client, room.id)
    rid = d["join_requests"][0]["id"]
    r = await post(
        host.client, f"/{room.id}/join-requests/{rid}/approve", {"version": d["version"]}
    )
    assert r.status_code == 409 and code_of(r) == "E-ROOM-2"
    r = await post(friend.client, f"/{room.id}/join-requests", {"version": d["version"]})
    assert r.status_code == 409 and code_of(r) == "E-ROOM-2"
    r = await post(
        host.client, f"/{room.id}/invites", {"phone": friend.phone, "version": d["version"]}
    )
    assert r.status_code == 409 and code_of(r) == "E-ROOM-2"


async def test_concurrent_approvals_never_exceed_eight(staff, admin, people):
    host = await people()
    guests = [await people() for _ in range(3)]
    room = (await room_for(staff, admin, host.code))["room"]
    for g in guests:
        await post(
            g.client, f"/{room.id}/join-requests", {"version": await version(g.client, room.id)}
        )
    await fill(room.id, 7)
    d = await detail(host.client, room.id)
    ids = [r["id"] for r in d["join_requests"]]
    assert len(ids) == 3
    results = await asyncio.gather(
        *(
            host.client.post(
                f"{ROOMS}/{room.id}/join-requests/{rid}/approve",
                json={"version": d["version"]},
                headers=idem(),
            )
            for rid in ids
        )
    )
    assert sorted(r.status_code for r in results) == [200, 409, 409]
    async with SessionLocal() as s:
        count = len(
            list(await s.scalars(select(PlayRoomMember).where(PlayRoomMember.room_id == room.id)))
        )
    assert count == 8


# ------------------------------------------------------------------ AC11, AC12: rời, mời ra, Host


async def join(host: Hv, guest: Hv, room_id: int) -> None:
    await post(
        guest.client, f"/{room_id}/join-requests", {"version": await version(guest.client, room_id)}
    )
    d = await detail(host.client, room_id)
    rid = next(r["id"] for r in d["join_requests"])
    r = await post(
        host.client, f"/{room_id}/join-requests/{rid}/approve", {"version": d["version"]}
    )
    assert r.status_code == 200, r.text


async def test_host_leaves_hands_over_then_last_leaves_closes(staff, admin, people):
    host, guest = await people("Host Cũ"), await people("Host Mới")
    room = (await room_for(staff, admin, host.code))["room"]
    await join(host, guest, room.id)

    r = await post(
        host.client, f"/{room.id}/leave", {"version": await version(host.client, room.id)}
    )
    assert r.status_code == 200, r.text
    assert r.json()["my_role"] == "outsider"
    g = await detail(guest.client, room.id)
    assert g["my_role"] == "host" and [m["role"] for m in g["members"]] == ["host"]
    assert any(
        i["kind"] == "room.host_assigned" for i in (await notifications(guest.client))["items"]
    )
    async with SessionLocal() as s:
        row = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "room.host_transferred", AuditLog.entity_code == str(room.id)
            )
        )
    assert row.detail["reason"] == "host_left"

    # Rời khi không còn trong phòng -> E-ROOM-6
    r = await post(host.client, f"/{room.id}/leave", {"version": g["version"]})
    assert r.status_code == 409 and code_of(r) == "E-ROOM-6"
    # Người cuối rời -> phòng đóng
    r = await post(guest.client, f"/{room.id}/leave", {"version": g["version"]})
    assert r.status_code == 200 and r.json()["status"] == "closed"


async def test_kick_and_transfer_host(staff, admin, people):
    host, a, b = await people("Chủ"), await people("Người A"), await people("Người B")
    room = (await room_for(staff, admin, host.code))["room"]
    await join(host, a, room.id)
    await join(host, b, room.id)
    d = await detail(host.client, room.id)
    a_id = next(m["id"] for m in d["members"] if m["display_name"] == "Người A")
    b_id = next(m["id"] for m in d["members"] if m["display_name"] == "Người B")
    me_id = next(m["id"] for m in d["members"] if m["is_me"])

    r = await post(a.client, f"/{room.id}/members/{b_id}/kick", {"version": d["version"]})
    assert r.status_code == 403 and code_of(r) == "E-ROOM-7"
    r = await post(host.client, f"/{room.id}/members/{me_id}/kick", {"version": d["version"]})
    assert r.status_code == 404
    r = await post(host.client, f"/{room.id}/members/{a_id}/kick", {"version": d["version"]})
    assert r.status_code == 200, r.text
    assert "Người A" not in [m["display_name"] for m in r.json()["members"]]
    assert any(i["kind"] == "room.kicked" for i in (await notifications(a.client))["items"])
    async with SessionLocal() as s:
        assert await s.scalar(
            select(AuditLog.id).where(
                AuditLog.action == "room.kicked", AuditLog.entity_code == str(room.id)
            )
        )
    # Bị mời ra vẫn xin vào lại được
    r2 = await post(a.client, f"/{room.id}/join-requests", {"version": r.json()["version"]})
    assert r2.status_code == 200 and r2.json()["my_join_pending"] is True

    v = await version(host.client, room.id)
    r = await post(host.client, f"/{room.id}/members/{b_id}/transfer-host", {"version": v})
    assert r.status_code == 200 and r.json()["my_role"] == "member"
    assert (await detail(b.client, room.id))["my_role"] == "host"
    # Host cũ hết quyền
    r = await post(host.client, f"/{room.id}/members/{b_id}/kick", {"version": r.json()["version"]})
    assert r.status_code in (403, 404)


async def test_writes_need_idempotency_key_and_origin(staff, admin, people):
    host, guest = await people(), await people()
    room = (await room_for(staff, admin, host.code))["room"]
    r = await guest.client.post(f"{ROOMS}/{room.id}/join-requests", json={"version": room.version})
    assert r.status_code == 400 and code_of(r) == "E-SEC-2"
    key = idem()
    r1 = await guest.client.post(
        f"{ROOMS}/{room.id}/join-requests", json={"version": room.version}, headers=key
    )
    r2 = await guest.client.post(
        f"{ROOMS}/{room.id}/join-requests", json={"version": room.version}, headers=key
    )
    assert r1.status_code == r2.status_code == 200
    assert r2.headers.get("idempotent-replayed") == "true"
    async with _client() as other:
        other.cookies = guest.client.cookies
        other.headers.pop("Origin")
        r = await other.post(
            f"{ROOMS}/{room.id}/join-requests", json={"version": room.version}, headers=idem()
        )
    assert r.status_code == 403


# ------------------------------------------------------------------ AC3: đóng phòng


async def test_tick_closes_room_and_blocks_writes(staff, admin, people):
    host, guest, friend = await people(), await people(), await people()
    room = (await room_for(staff, admin, host.code))["room"]
    await post(guest.client, f"/{room.id}/join-requests", {"version": room.version})
    await post(
        host.client, f"/{room.id}/invites", {"phone": friend.phone, "version": room.version + 1}
    )
    past = datetime.now(UTC) - timedelta(minutes=11)
    async with SessionLocal() as s:
        await s.execute(
            update(PlayRoom)
            .where(PlayRoom.id == room.id)
            .values(start_at=past - timedelta(hours=1), end_at=past)
        )
        await s.commit()
    # Quá giờ nhưng job chưa chạy: vẫn chặn ghi
    v = await version(host.client, room.id)
    r = await post(guest.client, f"/{room.id}/join-requests", {"version": v})
    assert r.status_code == 409 and code_of(r) == "E-ROOM-1"

    async with SessionLocal() as s:
        await lifecycle.tick(s)
    async with SessionLocal() as s:
        r_room = await s.get(PlayRoom, room.id)
        statuses = set(
            await s.scalars(
                select(PlayRoomRequest.status).where(PlayRoomRequest.room_id == room.id)
            )
        )
    assert r_room.status == "closed" and r_room.closed_at is not None
    assert statuses == {"expired"}
    d = await detail(host.client, room.id)  # vẫn xem được
    assert d["status"] == "closed" and d["phase"] == "closed"
    assert room.id not in [c["id"] for c in (await host.client.get(ROOMS)).json()["items"]]
    iid = (await detail(friend.client, room.id))["my_invite_id"]
    assert iid is None
    r = await post(host.client, f"/{room.id}/leave", {"version": d["version"]})
    assert r.status_code == 409 and code_of(r) == "E-ROOM-1"


async def test_tick_backfills_missing_rooms(staff, admin, people):
    host = await people()
    info = await room_for(staff, admin, host.code)
    async with SessionLocal() as s:
        await s.execute(delete(PlayRoom).where(PlayRoom.booking_code == info["code"]))
        await s.commit()
    async with SessionLocal() as s:
        created, _ = await lifecycle.tick(s)
    assert created >= 1
    async with SessionLocal() as s:
        assert await s.scalar(select(PlayRoom.id).where(PlayRoom.booking_code == info["code"]))


# ------------------------------------------------------------------ AC22: thông báo


async def test_notifications_read_and_isolation(staff, admin, people):
    host, guest = await people(), await people()
    room = (await room_for(staff, admin, host.code))["room"]
    await post(guest.client, f"/{room.id}/join-requests", {"version": room.version})
    await post(
        host.client, f"/{room.id}/invites", {"phone": guest.phone, "version": room.version + 1}
    )

    n = await notifications(host.client)
    assert n["unread_count"] == 1 and n["items"][0]["read"] is False
    nid = n["items"][0]["id"]
    # Thông báo của người khác -> 404 (SEC6)
    r = await guest.client.post(f"{NOTI}/{nid}/read")
    assert r.status_code == 404
    r = await host.client.post(f"{NOTI}/{nid}/read")
    assert r.status_code == 204
    n = await notifications(host.client)
    assert n["unread_count"] == 0 and n["items"][0]["read"] is True
    assert (await host.client.get(NOTI, params={"unread": "true"})).json()["items"] == []

    assert (await notifications(guest.client))["unread_count"] == 1
    r = await guest.client.post(f"{NOTI}/read-all")
    assert r.status_code == 204 and (await notifications(guest.client))["unread_count"] == 0
    async with SessionLocal() as s:
        payloads = [
            json.dumps(p)
            for p in await s.scalars(
                select(MemberNotification.payload).where(
                    MemberNotification.customer_id.in_([host.customer_id, guest.customer_id])
                )
            )
        ]
    assert payloads and all(host.phone not in p and guest.phone not in p for p in payloads)


async def test_notification_event_published_after_commit(staff, admin, people):
    host, guest = await people(), await people()
    room = (await room_for(staff, admin, host.code))["room"]
    seen: list[dict] = []

    async def spy(payload: dict) -> None:
        seen.append(payload)

    events.subscribe("member.notification_created")(spy)
    try:
        await post(guest.client, f"/{room.id}/join-requests", {"version": room.version})
        # Lỗi (version cũ) -> rollback, không phát
        await post(guest.client, f"/{room.id}/join-requests", {"version": room.version})
    finally:
        events._handlers["member.notification_created"].remove(spy)
    assert len(seen) == 1
    assert seen[0]["customer_id"] == host.customer_id and seen[0]["kind"] == "room.join_requested"
    async with SessionLocal() as s:
        assert await s.get(MemberNotification, seen[0]["id"]) is not None
