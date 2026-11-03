"""T-027: Host tự xếp đội hình -> trận ``drawn`` như kết quả bốc."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.play_rooms.models import PlayRoom
from tests import test_play_rooms as base
from tests.conftest import idem
from tests.test_play_room_matches import setup_room
from tests.test_play_rooms import ROOMS, code_of, detail, post

people = base.people  # fixture dùng chung (hội viên có tài khoản liên kết)


async def put_lineup(client, room_id: int, a: list[int], b: list[int], version: int, key=None):
    return await client.put(
        f"{ROOMS}/{room_id}/lineup",
        json={"team_a": a, "team_b": b, "version": version},
        headers=key or idem(),
    )


def ids(d: dict) -> list[int]:
    return [m["id"] for m in d["members"]]


def team_ids(d: dict, side: str) -> list[int]:
    return [p["member_id"] for p in d["current_match"][side]]


async def test_host_sets_lineup_replay_and_start(staff, admin, people):
    host, room = await setup_room(staff, admin, people, players=5)
    d = await detail(host.client, room.id)
    m = ids(d)
    waiting_before = {x["id"]: x["waiting_since"] for x in d["members"]}

    key = idem()
    r1 = await put_lineup(host.client, room.id, [m[0], m[3]], [m[1], m[4]], d["version"], key)
    assert r1.status_code == 200, r1.text
    d = r1.json()
    cm = d["current_match"]
    assert (cm["no"], cm["status"], cm["format"]) == (1, "drawn", "2v2")
    assert team_ids(d, "team_a") == [m[0], m[3]] and team_ids(d, "team_b") == [m[1], m[4]]
    assert {x["id"]: x["waiting_since"] for x in d["members"]} == waiting_before  # AC8
    # Gửi lại cùng key -> kết quả cũ
    r2 = await put_lineup(host.client, room.id, [m[0], m[3]], [m[1], m[4]], 1, key)
    assert r2.status_code == 200 and r2.headers.get("idempotent-replayed") == "true"
    assert r2.json() == r1.json()

    async with SessionLocal() as s:
        row = await s.scalar(
            select(AuditLog)
            .where(AuditLog.action == "room.lineup_set", AuditLog.entity_code == str(room.id))
            .order_by(AuditLog.id.desc())
        )
    assert row.detail["match_no"] == 1 and len(row.detail["team_a"]) == 2
    assert host.customer_id in row.detail["team_a"] and host.phone not in str(row.detail)

    # Xếp lại / bốc lại sau khi xếp tay: vẫn trận #1, thay đội hình
    r = await put_lineup(host.client, room.id, [m[1], m[2]], [m[3], m[4]], d["version"])
    assert r.status_code == 200 and r.json()["current_match"]["no"] == 1
    assert team_ids(r.json(), "team_a") == [m[1], m[2]]
    r = await post(host.client, f"/{room.id}/draw", {"version": r.json()["version"]})
    assert r.status_code == 200 and r.json()["current_match"]["no"] == 1

    # Bắt đầu trận xếp tay như trận bốc; đang chơi -> khóa xếp
    r = await put_lineup(host.client, room.id, [m[0], m[1]], [m[2], m[3]], r.json()["version"])
    # Dời cả end_at: chỉ dời start_at thì 5 phút cuối của giờ start > end (ck_play_room_range)
    soon = datetime.now(UTC) + timedelta(minutes=5)
    async with SessionLocal() as s:
        await s.execute(
            update(PlayRoom)
            .where(PlayRoom.id == room.id)
            .values(start_at=soon, end_at=soon + timedelta(hours=1))
        )
        await s.commit()
    r = await post(host.client, f"/{room.id}/start", {"version": r.json()["version"]})
    assert r.status_code == 200, r.text
    d = r.json()
    playing = {x["id"] for x in d["members"] if x["queue_state"] == "playing"}
    assert playing == {m[0], m[1], m[2], m[3]}
    r = await put_lineup(host.client, room.id, [m[0], m[4]], [m[1], m[2]], d["version"])
    assert r.status_code == 409 and code_of(r) == "E-ROOM-11"


async def test_lineup_validation_and_permissions(staff, admin, people):
    host, room = await setup_room(staff, admin, people, players=4)
    guest = await people("Người Ngoài")
    d = await detail(host.client, room.id)
    m, v = ids(d), d["version"]

    bad = [
        ([m[0]], [m[1], m[2]]),  # thiếu người
        ([m[0], m[1]], [m[2], m[3], m[0]]),  # thừa (schema chặn > 2)
        ([m[0], m[1]], [m[1], m[2]]),  # trùng người
        ([m[0], m[1]], [m[2], 999_999_999]),  # không ở phòng
    ]
    for a, b in bad:
        r = await put_lineup(host.client, room.id, a, b, v)
        assert r.status_code == 422, (a, b, r.text)
        if len(b) <= 2:
            assert code_of(r) == "E-ROOM-12" and r.json()["detail"]["message"] == (
                "Đội hình không hợp lệ."
            )
    r = await put_lineup(guest.client, room.id, [m[0], m[1]], [m[2], m[3]], v)
    assert r.status_code == 403 and code_of(r) == "E-ROOM-7"
    r = await put_lineup(host.client, room.id, [m[0], m[1]], [m[2], m[3]], v - 1)
    assert r.status_code == 409 and code_of(r) == "E-ROOM-6"
    r = await host.client.put(
        f"{ROOMS}/{room.id}/lineup", json={"team_a": [], "team_b": [], "version": v}
    )
    assert r.status_code == 400  # thiếu Idempotency-Key

    # 1 vs 1: mỗi đội 1 người; đổi thể thức xóa đội hình (AC8)
    r = await host.client.put(
        f"{ROOMS}/{room.id}/format", json={"format": "1v1", "version": v}, headers=idem()
    )
    assert r.status_code == 200, r.text
    r = await put_lineup(host.client, room.id, [m[0], m[1]], [m[2], m[3]], r.json()["version"])
    assert r.status_code == 422 and code_of(r) == "E-ROOM-12"
    d = await detail(host.client, room.id)
    r = await put_lineup(host.client, room.id, [m[2]], [m[0]], d["version"])
    assert r.status_code == 200, r.text
    assert team_ids(r.json(), "team_a") == [m[2]]
    r = await host.client.put(
        f"{ROOMS}/{room.id}/format",
        json={"format": "2v2", "version": r.json()["version"]},
        headers=idem(),
    )
    assert r.status_code == 200 and r.json()["current_match"] is None


async def test_kicked_member_clears_lineup(staff, admin, people):
    host, room = await setup_room(staff, admin, people, players=5)
    d = await detail(host.client, room.id)
    m = ids(d)
    r = await put_lineup(host.client, room.id, [m[0], m[1]], [m[2], m[3]], d["version"])
    assert r.status_code == 200
    r = await post(host.client, f"/{room.id}/members/{m[3]}/kick", {"version": r.json()["version"]})
    assert r.status_code == 200, r.text
    assert r.json()["current_match"] is None  # Q7 T-017: đội hình bị xóa
