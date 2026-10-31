"""T-017 mốc 2: bốc, bắt đầu, nhập tỉ số, Lịch sử trận, Xếp hạng, ETag (AC13–AC21)."""

from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.play_rooms import lifecycle
from app.modules.play_rooms.matches import Waiting, pick, split_teams
from app.modules.play_rooms.models import PlayMatch, PlayRoom, PlayRoomMember
from tests import test_play_rooms as base
from tests.conftest import idem
from tests.test_play_rooms import ROOMS, code_of, detail, fill, post, room_for

people = base.people  # fixture dùng chung (hội viên có tài khoản liên kết)

T0 = datetime(2026, 10, 31, 10, tzinfo=UTC)


def at(minutes: int) -> datetime:
    return T0 + timedelta(minutes=minutes)


# ------------------------------------------------------------------ AC15: thuật toán bốc


def test_first_draw_is_fully_random():
    waiting = [Waiting(i, at(i)) for i in range(1, 7)]  # giờ vào khác nhau nhưng chưa ai chơi
    seen: Counter[int] = Counter()
    for _ in range(600):
        chosen = pick(waiting, 4, fresh=True)
        assert len(set(chosen)) == 4
        seen.update(chosen)
    # Mỗi người kỳ vọng 400 lần (4/6 × 600); cho biên rộng để không chập chờn
    assert all(300 < seen[i] < 500 for i in range(1, 7)), seen


def test_longest_waiting_first():
    waiting = [Waiting(i, at(10 - i)) for i in range(1, 7)]  # người 6 chờ lâu nhất
    for _ in range(50):
        assert sorted(pick(waiting, 4, fresh=False)) == [3, 4, 5, 6]


def test_ties_at_cutoff_are_drawn_at_random():
    waiting = [
        Waiting(1, at(0)),
        Waiting(2, at(1)),
        Waiting(3, at(5)),
        Waiting(4, at(5)),
        Waiting(5, at(5)),
        Waiting(6, at(9)),
    ]
    seen: Counter[int] = Counter()
    for _ in range(300):
        chosen = pick(waiting, 4, fresh=False)
        assert {1, 2} <= set(chosen) and 6 not in chosen
        seen.update(chosen)
    assert all(seen[i] > 100 for i in (3, 4, 5)), seen  # kỳ vọng 200 mỗi người


def test_split_teams_random_halves():
    sides: Counter[frozenset[int]] = Counter()
    for _ in range(300):
        a, b = split_teams([1, 2, 3, 4])
        assert len(a) == len(b) == 2 and set(a) | set(b) == {1, 2, 3, 4}
        sides[frozenset(a)] += 1
    assert len(sides) == 6  # mọi cách chia đều xuất hiện


# ------------------------------------------------------------------ luồng một trận


async def v(client, room_id: int) -> int:
    return (await detail(client, room_id))["version"]


async def setup_room(staff, admin, people, players: int = 4):
    host = await people("Chủ Phòng")
    room = (await room_for(staff, admin, host.code))["room"]
    await fill(room.id, players)
    return host, room


async def test_draw_start_save_flow(staff, admin, people):
    host, room = await setup_room(staff, admin, people)
    guest = await people("Người Xem")

    r = await post(guest.client, f"/{room.id}/draw", {"version": await v(host.client, room.id)})
    assert r.status_code == 403 and code_of(r) == "E-ROOM-7"
    r = await post(host.client, f"/{room.id}/draw", {"version": await v(host.client, room.id)})
    assert r.status_code == 200, r.text
    m = r.json()["current_match"]
    assert (m["no"], m["status"], m["format"]) == (1, "drawn", "2v2")
    assert len(m["team_a"]) == len(m["team_b"]) == 2
    # Bốc lại: vẫn trận #1
    r = await post(host.client, f"/{room.id}/draw", {"version": r.json()["version"]})
    assert r.json()["current_match"]["no"] == 1

    # Chưa tới 15 phút trước giờ chơi -> E-ROOM-10
    async with SessionLocal() as s:
        await s.execute(
            update(PlayRoom)
            .where(PlayRoom.id == room.id)
            .values(
                start_at=datetime.now(UTC) + timedelta(minutes=20),
                end_at=datetime.now(UTC) + timedelta(minutes=80),
            )
        )
        await s.commit()
    r = await post(host.client, f"/{room.id}/start", {"version": r.json()["version"]})
    assert r.status_code == 409 and code_of(r) == "E-ROOM-10"
    async with SessionLocal() as s:
        await s.execute(
            update(PlayRoom)
            .where(PlayRoom.id == room.id)
            .values(start_at=datetime.now(UTC) + timedelta(minutes=14))
        )
        await s.commit()
    d = await detail(host.client, room.id)
    r = await post(host.client, f"/{room.id}/start", {"version": d["version"]})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["current_match"]["status"] == "playing" and d["current_match"]["started_at"]
    assert [m["queue_state"] for m in d["members"]] == ["playing"] * 4

    # Đang chơi: không bốc / đổi thể thức / rời / mời ra
    r = await post(host.client, f"/{room.id}/draw", {"version": d["version"]})
    assert r.status_code == 409 and code_of(r) == "E-ROOM-11"
    r = await host.client.put(
        f"{ROOMS}/{room.id}/format", json={"format": "1v1", "version": d["version"]}, headers=idem()
    )
    assert r.status_code == 409 and code_of(r) == "E-ROOM-11"
    r = await post(host.client, f"/{room.id}/leave", {"version": d["version"]})
    assert r.status_code == 409 and code_of(r) == "E-ROOM-5"
    assert r.json()["detail"]["match_no"] == 1
    other = next(m["id"] for m in d["members"] if not m["is_me"])
    r = await post(host.client, f"/{room.id}/members/{other}/kick", {"version": d["version"]})
    assert r.status_code == 409 and code_of(r) == "E-ROOM-5"

    # Tỉ số sai -> E-ROOM-9
    for a, b in ((15, 15), (100, 3), (-1, 21)):
        r = await post(
            host.client,
            f"/{room.id}/matches/1/result",
            {"score_a": a, "score_b": b, "version": d["version"]},
        )
        assert r.status_code == 422 and code_of(r) == "E-ROOM-9"
    r = await post(
        guest.client,
        f"/{room.id}/matches/1/result",
        {"score_a": 21, "score_b": 15, "version": d["version"]},
    )
    assert r.status_code == 403

    key = idem()
    body = {"score_a": 21, "score_b": 15, "version": d["version"]}
    r1 = await host.client.post(f"{ROOMS}/{room.id}/matches/1/result", json=body, headers=key)
    assert r1.status_code == 200, r1.text
    r2 = await host.client.post(f"{ROOMS}/{room.id}/matches/1/result", json=body, headers=key)
    assert r2.status_code == 200 and r2.headers.get("idempotent-replayed") == "true"
    assert r2.json() == r1.json()
    r3 = await post(host.client, f"/{room.id}/matches/1/result", body)  # key khác
    assert r3.status_code == 409 and code_of(r3) == "E-ROOM-6"
    after = r1.json()
    assert after["current_match"] is None
    assert [m["queue_state"] for m in after["members"]] == ["waiting"] * 4
    async with SessionLocal() as s:
        [match] = list(await s.scalars(select(PlayMatch).where(PlayMatch.room_id == room.id)))
        audit_row = await s.scalar(
            select(AuditLog).where(
                AuditLog.action == "room.match_saved", AuditLog.entity_code == str(room.id)
            )
        )
    assert (match.status, match.score_a, match.score_b, match.winner) == ("finished", 21, 15, "a")
    assert (audit_row.detail["score_a"], audit_row.detail["score_b"]) == (21, 15)

    # AC19 Lịch sử, AC20 Xếp hạng (người xem ngoài phòng vẫn đọc được)
    hist = (await guest.client.get(f"{ROOMS}/{room.id}/matches")).json()
    assert (hist["total"], hist["count_2v2"], hist["count_1v1"]) == (1, 1, 0)
    row = hist["items"][0]
    assert (row["no"], row["score_a"], row["score_b"], row["winner"]) == (1, 21, 15, "a")
    assert len(row["team_a"]) == 2
    only_1v1 = await guest.client.get(f"{ROOMS}/{room.id}/matches", params={"format": "1v1"})
    assert only_1v1.json()["items"] == [] and only_1v1.json()["total"] == 1
    rank = (await host.client.get(f"{ROOMS}/{room.id}/ranking")).json()["items"]
    assert [(x["rank"], x["wins"], x["losses"], x["played"]) for x in rank] == [
        (1, 1, 0, 1),
        (1, 1, 0, 1),
        (3, 0, 1, 1),
        (3, 0, 1, 1),
    ]
    assert [x["win_rate"] for x in rank] == [1.0, 1.0, 0.0, 0.0]
    assert sum(x["is_me"] for x in rank) == 1


async def test_next_draw_prefers_those_who_waited(staff, admin, people):
    """Đánh xong về cuối Hàng chờ: lượt sau ưu tiên người chưa được chơi."""
    host, room = await setup_room(staff, admin, people, players=4)
    d = await detail(host.client, room.id)
    d = (await post(host.client, f"/{room.id}/draw", {"version": d["version"]})).json()
    d = (await post(host.client, f"/{room.id}/start", {"version": d["version"]})).json()
    played = {p["member_id"] for p in d["current_match"]["team_a"] + d["current_match"]["team_b"]}
    await fill(room.id, 6)  # 2 người mới vào lúc trận đang chơi
    d = await detail(host.client, room.id)
    d = (
        await post(
            host.client,
            f"/{room.id}/matches/1/result",
            {"score_a": 10, "score_b": 21, "version": d["version"]},
        )
    ).json()
    newcomers = {m["id"] for m in d["members"]} - played
    assert len(newcomers) == 2
    d = (await post(host.client, f"/{room.id}/draw", {"version": d["version"]})).json()
    m = d["current_match"]
    assert m["no"] == 2
    assert newcomers <= {p["member_id"] for p in m["team_a"] + m["team_b"]}


async def test_format_and_not_enough_players(staff, admin, people):
    host, room = await setup_room(staff, admin, people, players=3)
    d = await detail(host.client, room.id)
    r = await post(host.client, f"/{room.id}/draw", {"version": d["version"]})
    assert r.status_code == 409 and code_of(r) == "E-ROOM-8"
    r = await post(host.client, f"/{room.id}/start", {"version": d["version"]})
    assert r.status_code == 409 and code_of(r) == "E-ROOM-8"  # chưa bốc

    r = await host.client.put(
        f"{ROOMS}/{room.id}/format", json={"format": "1v1", "version": d["version"]}, headers=idem()
    )
    assert r.status_code == 200 and r.json()["format"] == "1v1"
    d = (await post(host.client, f"/{room.id}/draw", {"version": r.json()["version"]})).json()
    m = d["current_match"]
    assert m["format"] == "1v1" and len(m["team_a"]) == len(m["team_b"]) == 1
    # Đổi thể thức khi đã bốc -> xóa kết quả bốc
    r = await host.client.put(
        f"{ROOMS}/{room.id}/format", json={"format": "2v2", "version": d["version"]}, headers=idem()
    )
    assert r.status_code == 200 and r.json()["current_match"] is None


async def test_leaving_drawn_player_clears_draw(staff, admin, people):
    host, room = await setup_room(staff, admin, people, players=1)
    guest = await people()
    d = await detail(guest.client, room.id)
    await post(guest.client, f"/{room.id}/join-requests", {"version": d["version"]})
    d = await detail(host.client, room.id)
    rid = d["join_requests"][0]["id"]
    d = (
        await post(
            host.client, f"/{room.id}/join-requests/{rid}/approve", {"version": d["version"]}
        )
    ).json()
    d = (
        await host.client.put(
            f"{ROOMS}/{room.id}/format",
            json={"format": "1v1", "version": d["version"]},
            headers=idem(),
        )
    ).json()
    d = (await post(host.client, f"/{room.id}/draw", {"version": d["version"]})).json()
    assert d["current_match"]["status"] == "drawn"
    r = await post(guest.client, f"/{room.id}/leave", {"version": d["version"]})
    assert r.status_code == 200, r.text  # đã bốc nhưng chưa chơi -> rời được
    assert (await detail(host.client, room.id))["current_match"] is None


async def test_closing_abandons_playing_match(staff, admin, people):
    host, room = await setup_room(staff, admin, people)
    d = await detail(host.client, room.id)
    d = (await post(host.client, f"/{room.id}/draw", {"version": d["version"]})).json()
    await post(host.client, f"/{room.id}/start", {"version": d["version"]})
    past = datetime.now(UTC) - timedelta(minutes=11)
    async with SessionLocal() as s:
        await s.execute(
            update(PlayRoom)
            .where(PlayRoom.id == room.id)
            .values(start_at=past - timedelta(hours=1), end_at=past)
        )
        await s.commit()
    async with SessionLocal() as s:
        await lifecycle.tick(s)
    async with SessionLocal() as s:
        match = await s.scalar(select(PlayMatch).where(PlayMatch.room_id == room.id))
        states = set(
            await s.scalars(
                select(PlayRoomMember.queue_state).where(PlayRoomMember.room_id == room.id)
            )
        )
    assert match.status == "abandoned" and match.score_a is None and match.ended_at
    assert states == {"waiting"}
    hist = (await host.client.get(f"{ROOMS}/{room.id}/matches")).json()
    assert hist["total"] == 0  # không tính trận bỏ dở
    assert (await host.client.get(f"{ROOMS}/{room.id}/ranking")).json()["items"] == []


async def test_host_leaving_with_no_eligible_member_hides_room(staff, admin, people):
    """Không còn ai đủ điều kiện làm Host: vẫn chuyển ngẫu nhiên, phòng ẩn theo luật đọc."""
    host, room = await setup_room(staff, admin, people, players=3)
    d = await detail(host.client, room.id)
    r = await post(host.client, f"/{room.id}/leave", {"version": d["version"]})
    assert r.status_code == 200, r.text
    async with SessionLocal() as s:
        r_room = await s.get(PlayRoom, room.id)
    assert r_room.host_customer_id < 0 and r_room.status == "open"  # thành viên giả làm Host
    assert (await host.client.get(f"{ROOMS}/{room.id}")).status_code == 404


# ------------------------------------------------------------------ AC21: ETag / 304


async def test_etag_304_until_room_changes(staff, admin, people):
    host, room = await setup_room(staff, admin, people)
    r = await host.client.get(f"{ROOMS}/{room.id}")
    etag = r.headers["etag"]
    assert etag.startswith('W/"')
    r = await host.client.get(f"{ROOMS}/{room.id}", headers={"If-None-Match": etag})
    assert r.status_code == 304 and r.content == b""
    lst = await host.client.get(ROOMS)
    r = await host.client.get(ROOMS, headers={"If-None-Match": lst.headers["etag"]})
    assert r.status_code == 304

    d = await detail(host.client, room.id)
    await post(host.client, f"/{room.id}/draw", {"version": d["version"]})
    r = await host.client.get(f"{ROOMS}/{room.id}", headers={"If-None-Match": etag})
    assert r.status_code == 200 and r.headers["etag"] != etag
    for path in ("matches", "ranking"):
        first = await host.client.get(f"{ROOMS}/{room.id}/{path}")
        again = await host.client.get(
            f"{ROOMS}/{room.id}/{path}", headers={"If-None-Match": first.headers["etag"]}
        )
        assert again.status_code == 304
