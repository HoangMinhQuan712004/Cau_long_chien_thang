# ruff: noqa: E501, F811
"""QA T-017 mốc 2: bốc, bắt đầu, nhập tỉ số, Lịch sử trận, Xếp hạng, ETag/304 (AC13–AC21, AC26 `room.match_saved`; SEC1, SEC3, SEC4, SEC5).

Viết từ spec `T-017-phong-choi.md` + handoff mốc 2, độc lập với `test_play_room_matches.py` của BACKEND.
Chỉ Host đăng nhập; người chơi khác là hội viên do quầy tạo (Admin API) và được đưa vào phòng bằng SQL, nên không chạm giới hạn đăng ký 10 lượt/giờ/IP.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import delete

from app.core.db import SessionLocal
from app.modules.auth.models import User
from app.modules.members.models import Customer
from tests.conftest import API, idem, unique_phone
from tests.qa_rooms import ROOMS, act, detail, err, find_room, make_room, people, q, tick, x  # noqa: F401

M = f"{API}/members"


@pytest.fixture
async def seats():
    """``await seats(admin, room_id, n)`` -> n hội viên do quầy tạo, đã ngồi trong Hàng chờ. Dọn khi xong."""
    phones: list[str] = []

    async def seat(admin, room_id: int, n: int) -> list[dict]:
        out = []
        for i in range(n):
            phone = unique_phone()
            phones.append(phone)
            name = f"QAM2 {uuid.uuid4().hex[:5]} {i}"
            r = await admin.post(M, json={"full_name": name, "phone": phone}, headers=idem())
            assert r.status_code == 201, r.text
            cid = (await q("SELECT id FROM customer WHERE phone=:p", p=phone))[0]["id"]
            await x(
                "INSERT INTO play_room_member (room_id, customer_id, queue_state, waiting_since, joined_at) VALUES (:r, :c, 'waiting', now(), now())",
                r=room_id,
                c=cid,
            )
            out.append({"id": cid, "name": name, "phone": phone})
        return out

    yield seat
    async with SessionLocal() as s:
        await s.execute(delete(Customer).where(Customer.phone.in_(phones)))
        await s.execute(delete(User).where(User.phone.in_(phones)))
        await s.commit()


async def room_with(admin, people, seats, n_extra: int):
    host = await people("Chủ Trận")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    extra = await seats(admin, rid, n_extra)
    return host, rid, extra, spec


async def hv(c, rid):
    return (await detail(c, rid))["version"]


async def draw(c, rid, **kw):
    return await act(c, rid, "/draw", {"version": await hv(c, rid)}, **kw)


async def start(c, rid):
    return await act(c, rid, "/start", {"version": await hv(c, rid)})


async def save(c, rid, no, a, b, *, headers=None, version=None):
    return await act(
        c,
        rid,
        f"/matches/{no}/result",
        {"score_a": a, "score_b": b, "version": await hv(c, rid) if version is None else version},
        headers=headers,
    )


async def set_format(c, rid, fmt, version=None):
    return await c.put(
        f"{ROOMS}/{rid}/format",
        json={"format": fmt, "version": await hv(c, rid) if version is None else version},
        headers=idem(),
    )


def ids_of(m: dict) -> list[int]:
    return [p["member_id"] for p in m["team_a"] + m["team_b"]]


async def play(c, rid, a, b):
    """bốc → bắt đầu → lưu tỉ số; trả (current_match lúc chơi, chi tiết sau khi lưu)."""
    d = (await draw(c, rid)).json()
    assert d["current_match"]["status"] == "drawn", d
    s = await start(c, rid)
    assert s.status_code == 200, s.text
    m = s.json()["current_match"]
    r = await save(c, rid, m["no"], a, b)
    assert r.status_code == 200, r.text
    return m, r.json()


async def baseline_audit() -> int:
    return (await q("SELECT coalesce(max(id),0) AS m FROM audit_log"))[0]["m"]


# ============================================================ AC14 thể thức


async def test_ac14_format_host_only_validation_and_clearing_the_draw(admin, people, seats):
    host, rid, _, _ = await room_with(admin, people, seats, 3)
    out = await people("Người Ngoài")
    for who in (out.client,):
        r = await set_format(who, rid, "1v1", version=await hv(who, rid))
        assert r.status_code == 403 and err(r)["code"] == "E-ROOM-7"
    for bad in ("3v3", "", "2V2", None):
        r = await host.client.put(
            f"{ROOMS}/{rid}/format",
            json={"format": bad, "version": await hv(host.client, rid)},
            headers=idem(),
        )
        assert r.status_code == 422, bad
    d = await detail(host.client, rid)
    assert d["format"] == "2v2"
    # đủ 4 người → bốc 2v2; đổi sang 1v1 khi đã bốc → xóa kết quả bốc
    drawn = (await draw(host.client, rid)).json()
    assert drawn["current_match"] and len(drawn["current_match"]["team_a"]) == 2
    r = await set_format(host.client, rid, "1v1")
    assert (
        r.status_code == 200 and r.json()["format"] == "1v1" and r.json()["current_match"] is None
    )
    d2 = (await draw(host.client, rid)).json()
    assert [len(d2["current_match"]["team_a"]), len(d2["current_match"]["team_b"])] == [1, 1]


async def test_ac14_draw_needs_enough_players_per_format(admin, people, seats):
    host, rid, _, _ = await room_with(admin, people, seats, 2)  # 3 người
    r = await draw(host.client, rid)
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-8"
    assert (await set_format(host.client, rid, "1v1")).status_code == 200
    assert (await draw(host.client, rid)).status_code == 200, "1v1 cần 2 người"
    # chỉ còn 1 người trong Hàng chờ → không bốc 1v1
    await x(
        "DELETE FROM play_room_member WHERE room_id=:r AND customer_id <> (SELECT host_customer_id FROM play_room WHERE id=:r)",
        r=rid,
    )
    r = await draw(host.client, rid)
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-8"


# ============================================================ AC15 thuật toán bốc


async def test_ac15_first_draw_is_random_across_all_waiting_members(admin, people, seats):
    host, rid, extra, _ = await room_with(admin, people, seats, 7)  # 8 người, chưa trận nào
    seen: dict[int, int] = {}
    v = await hv(host.client, rid)
    for _ in range(40):  # dùng version trả về để không tốn thêm request (giới hạn chung theo IP)
        r = await act(host.client, rid, "/draw", {"version": v})
        assert r.status_code == 200, r.text
        d = r.json()
        v = d["version"]
        chosen = ids_of(d["current_match"])
        assert len(chosen) == len(set(chosen)) == 4 and len(d["current_match"]["team_a"]) == 2
        for c in chosen:
            seen[c] = seen.get(c, 0) + 1
    assert len(seen) == 8, f"lần đầu mọi người đều có cơ hội: {seen}"
    assert all(3 < n < 37 for n in seen.values()), seen  # kỳ vọng 20 mỗi người


async def test_ac15_longest_waiting_get_priority_in_following_draws(admin, people, seats):
    host, rid, _, _ = await room_with(admin, people, seats, 5)  # 6 người
    m1, _ = await play(host.client, rid, 21, 10)
    first = set(ids_of(m1))
    waited = {m["id"] for m in (await detail(host.client, rid))["members"]} - first
    assert len(waited) == 2
    m2, _ = await play(host.client, rid, 15, 21)
    assert m2["no"] == 2 and waited <= set(ids_of(m2)), "người chờ lâu nhất vào trận kế"
    second = set(ids_of(m2))
    left_out = {m["id"] for m in (await detail(host.client, rid))["members"]} - second
    assert left_out <= first and len(left_out) == 2, (
        "2 người ngồi ngoài là 2 người đã đánh trận 1 mà không vào trận 2"
    )
    m3, _ = await play(host.client, rid, 21, 19)
    assert left_out <= set(ids_of(m3)), "…và họ được ưu tiên ở trận 3"


async def test_ac15_ties_at_the_cutoff_are_random(admin, people, seats):
    host, rid, _, _ = await room_with(admin, people, seats, 5)  # 6 người
    await play(host.client, rid, 21, 10)  # sau trận 1: 2 người chờ cũ + 4 người cùng mốc
    seen: dict[int, int] = {}
    for _ in range(50):
        m = (await draw(host.client, rid)).json()["current_match"]
        for c in ids_of(m):
            seen[c] = seen.get(c, 0) + 1
    assert len(seen) == 6
    ties = sorted(seen.values())[2:]  # 4 người cùng mốc chia nhau 2 chỗ
    assert all(n > 10 for n in ties), seen


# ============================================================ AC16 bắt đầu


async def test_ac16_start_rules_numbering_and_membership_states(admin, people, seats):
    host, rid, extra, _ = await room_with(admin, people, seats, 4)  # 5 người
    out = await people("Người Ngoài")
    r = await start(host.client, rid)
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-8", "chưa bốc"
    d = (await draw(host.client, rid)).json()
    assert d["current_match"]["no"] == 1 and d["current_match"]["status"] == "drawn"
    again = (await draw(host.client, rid)).json()
    assert again["current_match"]["no"] == 1, "bốc lại giữ số trận"
    for who in (out.client,):
        r = await act(who, rid, "/start", {"version": await hv(who, rid)})
        assert r.status_code == 403 and err(r)["code"] == "E-ROOM-7"
        r = await act(who, rid, "/draw", {"version": await hv(who, rid)})
        assert r.status_code == 403 and err(r)["code"] == "E-ROOM-7"
    # sớm hơn 15 phút → E-ROOM-10; trong 15 phút → được
    await x(
        "UPDATE play_room SET start_at = now() + interval '16 minutes', end_at = now() + interval '76 minutes' WHERE id=:i",
        i=rid,
    )
    r = await start(host.client, rid)
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-10"
    await x("UPDATE play_room SET start_at = now() + interval '14 minutes' WHERE id=:i", i=rid)
    r = await start(host.client, rid)
    assert r.status_code == 200, r.text
    d = r.json()
    drawn = set(ids_of(d["current_match"]))
    assert d["current_match"]["status"] == "playing" and d["current_match"]["started_at"]
    states = {m["id"]: m["queue_state"] for m in d["members"]}
    assert {mid for mid, st in states.items() if st == "playing"} == drawn and len(
        [1 for s in states.values() if s == "waiting"]
    ) == 1
    # đang chơi: chỉ một trận, bắt đầu/bốc/đổi thể thức đều bị chặn (E-ROOM-11), rời/mời ra người đang chơi → E-ROOM-5
    for coro in (start(host.client, rid), draw(host.client, rid)):
        r = await coro
        assert r.status_code == 409 and err(r)["code"] == "E-ROOM-11", r.text
    r = await set_format(host.client, rid, "1v1")
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-11"
    playing_other = next(
        m for m in d["members"] if m["queue_state"] == "playing" and not m["is_me"]
    )
    r = await act(
        host.client,
        rid,
        f"/members/{playing_other['id']}/kick",
        {"version": await hv(host.client, rid)},
    )
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-5"
    assert err(r).get("match_no") == 1


async def test_ac16_player_in_a_running_match_cannot_leave_but_a_waiting_one_can(
    admin, people, seats
):
    host, rid, extra, _ = await room_with(admin, people, seats, 4)
    assert (await draw(host.client, rid)).status_code == 200
    d = (await start(host.client, rid)).json()
    me_playing = next(m for m in d["members"] if m["is_me"])["queue_state"] == "playing"
    if me_playing:
        r = await act(host.client, rid, "/leave", {"version": d["version"]})
        assert (
            r.status_code == 409 and err(r)["code"] == "E-ROOM-5" and err(r).get("match_no") == 1
        ), r.text
    waiting = next(
        m
        for m in d["members"]
        if m["queue_state"] == "waiting" and not m["is_me"] and m["role"] != "host"
    )
    r = await act(host.client, rid, f"/members/{waiting['id']}/kick", {"version": d["version"]})
    assert r.status_code == 200, "mời ra người đang ở Hàng chờ được"


async def test_ac16_kicking_a_drawn_player_clears_the_draw_and_start_then_fails(
    admin, people, seats
):
    host, rid, _, _ = await room_with(admin, people, seats, 4)
    d = (await draw(host.client, rid)).json()
    victim = next(
        m for m in d["members"] if m["id"] in ids_of(d["current_match"]) and m["role"] != "host"
    )
    r = await act(host.client, rid, f"/members/{victim['id']}/kick", {"version": d["version"]})
    assert r.status_code == 200 and r.json()["current_match"] is None, (
        "bỏ kết quả bốc khi người được bốc bị mời ra"
    )
    r = await start(host.client, rid)
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-8"


# ============================================================ AC17 tỉ số + SEC4


async def test_ac17_result_validation_permissions_and_state(admin, people, seats):
    host, rid, _, _ = await room_with(admin, people, seats, 3)
    out = await people("Người Ngoài")
    r = await save(host.client, rid, 1, 21, 10)
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-6", "chưa có trận"
    await draw(host.client, rid)
    r = await save(host.client, rid, 1, 21, 10)
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-6", "trận mới bốc, chưa bắt đầu"
    d = (await start(host.client, rid)).json()
    v = d["version"]
    r = await save(out.client, rid, 1, 21, 10, version=await hv(out.client, rid))
    assert r.status_code == 403 and err(r)["code"] == "E-ROOM-7"
    r = await save(host.client, rid, 2, 21, 10, version=v)
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-6", "sai số trận"
    for a, b in ((15, 15), (0, 0), (100, 3), (3, 100), (-1, 5), (5, -1)):
        r = await save(host.client, rid, 1, a, b, version=v)
        assert r.status_code == 422 and err(r)["code"] == "E-ROOM-9", (a, b, r.text[:80])
        assert err(r)["message"] == "Tỉ số không hợp lệ (0–99, không hòa)."
    for a, b in (("x", 3), (1.5, 3), (None, 3), (3, None)):
        r = await act(
            host.client, rid, "/matches/1/result", {"score_a": a, "score_b": b, "version": v}
        )
        assert r.status_code == 422, (a, b)
    r = await act(host.client, rid, "/matches/1/result", {"score_a": 5, "version": v})
    assert r.status_code == 422
    assert (await q("SELECT status::text AS s FROM play_match WHERE room_id=:i", i=rid))[0][
        "s"
    ] == "playing", "tỉ số sai không làm đổi trận"
    r = await save(host.client, rid, 1, 99, 98, version=v)
    assert r.status_code == 200, "biên 99–98 hợp lệ"
    m = (
        await q(
            "SELECT score_a, score_b, winner, status::text AS s FROM play_match WHERE room_id=:i",
            i=rid,
        )
    )[0]
    assert (m["score_a"], m["score_b"], m["winner"], m["s"]) == (99, 98, "a", "finished")


async def test_ac17_zero_score_is_valid_and_winner_b_players_return_to_end_of_queue(
    admin, people, seats
):
    host, rid, _, _ = await room_with(admin, people, seats, 4)
    m, after = await play(host.client, rid, 0, 7)
    assert after["current_match"] is None and all(
        x["queue_state"] == "waiting" for x in after["members"]
    )
    row = (await q("SELECT winner, score_a, score_b FROM play_match WHERE room_id=:i", i=rid))[0]
    assert (row["winner"], row["score_a"], row["score_b"]) == ("b", 0, 7)
    ws = {x["id"]: x["waiting_since"] for x in after["members"]}
    played = set(ids_of(m))
    sit = [x for x in after["members"] if x["id"] not in played]
    assert sit and min(ws[i] for i in played) > max(x["waiting_since"] for x in sit), (
        "người vừa đánh vào cuối Hàng chờ"
    )


async def test_sec4_saved_result_cannot_be_changed_and_double_submit_saves_once(
    admin, people, seats
):
    host, rid, _, _ = await room_with(admin, people, seats, 3)
    base = await baseline_audit()
    await draw(host.client, rid)
    d = (await start(host.client, rid)).json()
    k = {"Idempotency-Key": str(uuid.uuid4())}
    body = (1, 21, 15, d["version"])
    r1 = await save(host.client, rid, body[0], body[1], body[2], headers=k, version=body[3])
    r2 = await save(host.client, rid, body[0], body[1], body[2], headers=k, version=body[3])
    assert (
        r1.status_code == r2.status_code == 200
        and r2.json() == r1.json()
        and r2.headers.get("idempotent-replayed") == "true"
    )
    r3 = await save(host.client, rid, 1, 5, 21, version=body[3])  # key khác, tỉ số khác
    assert r3.status_code == 409 and err(r3)["code"] == "E-ROOM-6"
    r4 = await save(
        host.client, rid, 1, 5, 21, version=r1.json()["version"]
    )  # version mới nhất vẫn không sửa được
    assert r4.status_code == 409 and err(r4)["code"] == "E-ROOM-6"
    for method, path in (
        ("put", "/matches/1/result"),
        ("patch", "/matches/1/result"),
        ("patch", "/matches/1"),
        ("delete", "/matches/1"),
        ("put", "/matches/1"),
    ):
        r = await getattr(host.client, method)(
            f"{ROOMS}/{rid}{path}",
            headers=idem(),
            **({} if method == "delete" else {"json": {"score_a": 1, "score_b": 0, "version": 9}}),
        )
        assert r.status_code in (404, 405), (method, path, r.status_code)
    row = await q(
        "SELECT score_a, score_b, status::text AS s FROM play_match WHERE room_id=:i", i=rid
    )
    assert len(row) == 1 and (row[0]["score_a"], row[0]["score_b"], row[0]["s"]) == (
        21,
        15,
        "finished",
    )
    n = (
        await q(
            "SELECT count(*) AS n FROM audit_log WHERE action='room.match_saved' AND id > :b",
            b=base,
        )
    )[0]["n"]
    assert n == 1, "mỗi trận một dòng nhật ký"


async def test_sec4_concurrent_saves_with_different_keys_save_exactly_one(admin, people, seats):
    host, rid, _, _ = await room_with(admin, people, seats, 3)
    base = await baseline_audit()
    await draw(host.client, rid)
    v = (await start(host.client, rid)).json()["version"]
    scores = [(21, 10), (10, 21), (21, 19), (3, 5), (30, 28)]
    res = await asyncio.gather(*[save(host.client, rid, 1, a, b, version=v) for a, b in scores])
    codes = sorted(r.status_code for r in res)
    assert codes == [200, 409, 409, 409, 409], codes
    assert all(err(r)["code"] == "E-ROOM-6" for r in res if r.status_code == 409)
    won = next(s for s, r in zip(scores, res, strict=True) if r.status_code == 200)
    row = await q("SELECT score_a, score_b FROM play_match WHERE room_id=:i", i=rid)
    assert len(row) == 1 and (row[0]["score_a"], row[0]["score_b"]) == won
    assert (
        await q(
            "SELECT count(*) AS n FROM audit_log WHERE action='room.match_saved' AND id > :b",
            b=base,
        )
    )[0]["n"] == 1


async def test_sec4_concurrent_double_click_with_the_same_key_saves_once(admin, people, seats):
    host, rid, _, _ = await room_with(admin, people, seats, 3)
    base = await baseline_audit()
    await draw(host.client, rid)
    v = (await start(host.client, rid)).json()["version"]
    k = {"Idempotency-Key": str(uuid.uuid4())}
    res = await asyncio.gather(
        *[save(host.client, rid, 1, 21, 15, headers=k, version=v) for _ in range(4)]
    )
    assert all(r.status_code in (200, 409) for r in res), [r.status_code for r in res]
    assert any(r.status_code == 200 for r in res)
    assert (
        len(await q("SELECT 1 FROM play_match WHERE room_id=:i AND status='finished'", i=rid)) == 1
    )
    assert (
        await q(
            "SELECT count(*) AS n FROM audit_log WHERE action='room.match_saved' AND id > :b",
            b=base,
        )
    )[0]["n"] == 1


# ============================================================ AC18 đóng phòng khi đang chơi


async def test_ac18_closing_while_playing_abandons_the_match_and_excludes_it_from_stats(
    admin, people, seats
):
    host, rid, _, _ = await room_with(admin, people, seats, 4)
    await play(host.client, rid, 21, 10)  # 1 trận đã lưu
    await draw(host.client, rid)
    assert (await start(host.client, rid)).status_code == 200
    await x(
        "UPDATE play_room SET end_at = now() - interval '11 minutes', start_at = now() - interval '71 minutes' WHERE id=:i",
        i=rid,
    )
    await tick()
    rows = await q(
        "SELECT no, status::text AS s, score_a, score_b FROM play_match WHERE room_id=:i ORDER BY no",
        i=rid,
    )
    assert [(r["no"], r["s"]) for r in rows] == [(1, "finished"), (2, "abandoned")] and rows[1][
        "score_a"
    ] is None
    d = await detail(host.client, rid)
    assert (
        d["status"] == "closed"
        and d["current_match"] is None
        and all(m["queue_state"] == "waiting" for m in d["members"])
    )
    hist = (await host.client.get(f"{ROOMS}/{rid}/matches")).json()
    assert hist["total"] == 1 and [i["no"] for i in hist["items"]] == [1]
    ranking = (await host.client.get(f"{ROOMS}/{rid}/ranking")).json()["items"]
    assert sum(x["played"] for x in ranking) == 4, "chỉ trận đã lưu được tính"
    r = await save(host.client, rid, 2, 21, 10, version=d["version"])
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-1"
    r = await draw(host.client, rid)
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-1"


# ============================================================ AC19 Lịch sử, AC20 Xếp hạng


def oracle(history: dict) -> dict[str, tuple[int, int]]:
    """{tên: (thắng, thua)} tính lại từ Lịch sử trận."""
    res: dict[str, list[int]] = {}
    for it in history["items"]:
        win, lose = (
            (it["team_a"], it["team_b"]) if it["winner"] == "a" else (it["team_b"], it["team_a"])
        )
        for p in win:
            res.setdefault(p, [0, 0])[0] += 1
        for p in lose:
            res.setdefault(p, [0, 0])[1] += 1
    return {k: (v[0], v[1]) for k, v in res.items()}


async def test_ac19_history_counts_filter_order_and_viewable_by_outsiders(admin, people, seats):
    host, rid, _, _ = await room_with(admin, people, seats, 4)
    out = await people("Người Ngoài")
    await play(host.client, rid, 21, 10)
    await set_format(host.client, rid, "1v1")
    await play(host.client, rid, 5, 21)
    await set_format(host.client, rid, "2v2")
    await play(host.client, rid, 21, 20)
    h = (await out.client.get(f"{ROOMS}/{rid}/matches")).json()
    assert (h["total"], h["count_2v2"], h["count_1v1"]) == (3, 2, 1)
    assert [i["no"] for i in h["items"]] == [3, 2, 1], "mới nhất trên cùng"
    row = h["items"][0]
    assert {
        "no",
        "format",
        "started_at",
        "ended_at",
        "team_a",
        "team_b",
        "score_a",
        "score_b",
        "winner",
    } <= set(row)
    assert (row["score_a"], row["score_b"], row["winner"], row["format"]) == (
        21,
        20,
        "a",
        "2v2",
    ) and len(row["team_a"]) == 2
    f1 = (await out.client.get(f"{ROOMS}/{rid}/matches", params={"format": "1v1"})).json()
    assert [i["no"] for i in f1["items"]] == [2] and f1["total"] == 3 and f1["count_1v1"] == 1, (
        "số đếm tính mọi thể thức"
    )
    assert (
        await out.client.get(f"{ROOMS}/{rid}/matches", params={"format": "3v3"})
    ).status_code == 422
    for p in (f"{ROOMS}/{rid}/matches", f"{ROOMS}/{rid}/ranking"):
        assert (await host.client.get(p.replace(str(rid), "999999"))).status_code == 404


async def test_ac20_ranking_matches_an_independent_oracle_with_tied_ranks(admin, people, seats):
    host, rid, _, _ = await room_with(admin, people, seats, 5)  # 6 người
    for a, b in ((21, 10), (8, 21), (21, 14), (12, 21)):
        await play(host.client, rid, a, b)
    h = (await host.client.get(f"{ROOMS}/{rid}/matches")).json()
    r = (await host.client.get(f"{ROOMS}/{rid}/ranking")).json()["items"]
    want = oracle(h)
    got = {row["display_name"]: (row["wins"], row["losses"]) for row in r}
    assert got == want, (got, want)
    for row in r:
        assert (
            row["played"] == row["wins"] + row["losses"]
            and abs(row["win_rate"] - row["wins"] / row["played"]) < 1e-3
        )
    keys = [(-row["wins"], -row["win_rate"]) for row in r]
    assert keys == sorted(keys), "xếp theo số thắng, bằng nhau thì tỉ lệ thắng"
    for row in r:
        better = sum(1 for y in r if (y["wins"], y["win_rate"]) > (row["wins"], row["win_rate"]))
        assert row["rank"] == better + 1, "đồng hạng khi bằng cả hai (1, 1, 3…)"
    assert any(r[i]["rank"] == r[i + 1]["rank"] for i in range(len(r) - 1)), (
        "kịch bản này có đồng hạng"
    )
    assert sum(row["is_me"] for row in r) <= 1


async def test_ac20_ranking_filter_by_format_and_leavers_keep_their_results(admin, people, seats):
    host, rid, extra, _ = await room_with(admin, people, seats, 4)
    m, _ = await play(host.client, rid, 21, 10)
    await set_format(host.client, rid, "1v1")
    await play(host.client, rid, 21, 3)
    r_all = (await host.client.get(f"{ROOMS}/{rid}/ranking")).json()["items"]
    r_1 = (await host.client.get(f"{ROOMS}/{rid}/ranking", params={"format": "1v1"})).json()[
        "items"
    ]
    r_2 = (await host.client.get(f"{ROOMS}/{rid}/ranking", params={"format": "2v2"})).json()[
        "items"
    ]
    assert (
        sum(x["played"] for x in r_1) == 2
        and sum(x["played"] for x in r_2) == 4
        and sum(x["played"] for x in r_all) == 6
    )
    assert (
        await host.client.get(f"{ROOMS}/{rid}/ranking", params={"format": "x"})
    ).status_code == 422
    # một người chơi rời → vẫn giữ kết quả với tên lúc đó
    d = await detail(host.client, rid)
    leaver = next(mm for mm in d["members"] if mm["role"] != "host")
    name = leaver["display_name"]
    assert (
        await act(host.client, rid, f"/members/{leaver['id']}/kick", {"version": d["version"]})
    ).status_code == 200
    after = (await host.client.get(f"{ROOMS}/{rid}/ranking")).json()["items"]
    assert name in {x["display_name"] for x in after} and sum(x["played"] for x in after) == 6
    hist = (await host.client.get(f"{ROOMS}/{rid}/matches")).json()
    assert name in {p for i in hist["items"] for p in i["team_a"] + i["team_b"]}


async def test_ac19_names_are_snapshots_taken_at_draw_time(admin, people, seats):
    host, rid, _, _ = await room_with(admin, people, seats, 3)
    m, _ = await play(host.client, rid, 21, 10)
    before = (await host.client.get(f"{ROOMS}/{rid}/matches")).json()["items"][0]
    me = (await host.client.get(f"{API}/member-area/me")).json()
    body = {
        k: me[k]
        for k in ("full_name", "nickname", "email", "tier", "racket", "show_on_records", "version")
    }
    assert (
        await host.client.put(
            f"{API}/member-area/me", json={**body, "nickname": "Đổi Tên Sau"}, headers=idem()
        )
    ).status_code == 200
    after = (await host.client.get(f"{ROOMS}/{rid}/matches")).json()["items"][0]
    assert after["team_a"] == before["team_a"] and after["team_b"] == before["team_b"], (
        "lịch sử giữ tên lúc bốc"
    )


# ============================================================ AC21 ETag / 304 + E-ROOM-6


async def test_ac21_etag_304_per_viewer_and_changes_after_writes(admin, people, seats):
    host, rid, _, spec = await room_with(admin, people, seats, 3)
    out = await people("Người Ngoài")
    for path in ("", "/matches", "/ranking"):
        a = await host.client.get(f"{ROOMS}/{rid}{path}")
        assert (
            a.status_code == 200
            and a.headers["etag"].startswith('W/"')
            and "no-cache" in a.headers["cache-control"]
            and "private" in a.headers["cache-control"]
        )
        b = await host.client.get(
            f"{ROOMS}/{rid}{path}", headers={"If-None-Match": a.headers["etag"]}
        )
        assert b.status_code == 304 and b.content == b""
    lst = await host.client.get(ROOMS)
    assert (
        await host.client.get(ROOMS, headers={"If-None-Match": lst.headers["etag"]})
    ).status_code == 304
    ha, oa = await host.client.get(f"{ROOMS}/{rid}"), await out.client.get(f"{ROOMS}/{rid}")
    assert ha.headers["etag"] != oa.headers["etag"], "ETag theo người xem"
    cross = await out.client.get(f"{ROOMS}/{rid}", headers={"If-None-Match": ha.headers["etag"]})
    assert cross.status_code == 200, "ETag của người khác không cho 304"
    # đổi trạng thái → 200 + ETag mới, cho cả hai phía
    await draw(host.client, rid)
    assert (
        await host.client.get(f"{ROOMS}/{rid}", headers={"If-None-Match": ha.headers["etag"]})
    ).status_code == 200
    assert (
        await out.client.get(f"{ROOMS}/{rid}", headers={"If-None-Match": oa.headers["etag"]})
    ).status_code == 200
    # yêu cầu vào phòng đổi nội dung mà Host đang polling
    ha2 = await host.client.get(f"{ROOMS}/{rid}")
    assert (
        await act(out.client, rid, "/join-requests", {"version": ha2.json()["version"]})
    ).status_code == 200
    assert (
        await host.client.get(f"{ROOMS}/{rid}", headers={"If-None-Match": ha2.headers["etag"]})
    ).status_code == 200
    h = await host.client.get(f"{ROOMS}/{rid}")
    stale = await host.client.get(
        f"{ROOMS}/{rid}", headers={"If-None-Match": 'W/"deadbeef", ' + h.headers["etag"]}
    )
    assert stale.status_code == 304, "danh sách nhiều ETag"
    # ranking/matches đổi sau khi lưu trận
    m_et = (await host.client.get(f"{ROOMS}/{rid}/matches")).headers["etag"]
    await start(host.client, rid)
    await save(host.client, rid, 1, 21, 10)
    assert (
        await host.client.get(f"{ROOMS}/{rid}/matches", headers={"If-None-Match": m_et})
    ).status_code == 200
    # phòng đã có thẻ danh sách
    assert (await find_room(host.client, spec["court"]["name"])) is not None


async def test_ac21_every_write_on_a_stale_version_is_e_room_6(admin, people, seats):
    host, rid, _, _ = await room_with(admin, people, seats, 3)
    old = await hv(host.client, rid)
    assert (await draw(host.client, rid)).status_code == 200  # version tăng
    for path, body in (
        ("/draw", {}),
        ("/start", {}),
        ("/matches/1/result", {"score_a": 3, "score_b": 1}),
    ):
        r = await act(host.client, rid, path, {**body, "version": old})
        assert r.status_code == 409 and err(r)["code"] == "E-ROOM-6", path
    r = await set_format(host.client, rid, "1v1", version=old)
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-6"
    assert (await detail(host.client, rid))["format"] == "2v2"


async def test_draw_replay_with_same_key_does_not_draw_twice(admin, people, seats):
    host, rid, _, _ = await room_with(admin, people, seats, 7)
    k = {"Idempotency-Key": str(uuid.uuid4())}
    v = await hv(host.client, rid)
    r1 = await act(host.client, rid, "/draw", {"version": v}, headers=k)
    r2 = await act(host.client, rid, "/draw", {"version": v}, headers=k)
    assert (
        r1.status_code == r2.status_code == 200
        and r2.json() == r1.json()
        and r2.headers.get("idempotent-replayed") == "true"
    )


# ============================================================ AC26 nhật ký trận


async def test_ac26_match_saved_audit_has_score_and_teams_without_phone(admin, people, seats):
    host, rid, extra, _ = await room_with(admin, people, seats, 3)
    base = await baseline_audit()
    m, _ = await play(host.client, rid, 21, 17)
    rows = await q(
        "SELECT actor_type, action, entity_code, detail::text AS d FROM audit_log WHERE action='room.match_saved' AND id > :b",
        b=base,
    )
    assert (
        len(rows) == 1
        and rows[0]["actor_type"] == "customer"
        and rows[0]["entity_code"] == str(rid)
    )
    d = rows[0]["d"]
    for want in ("21", "17"):
        assert want in d
    assert (
        host.phone not in d
        and all(e["phone"] not in d for e in extra)
        and not any(p[1:] in d for p in (host.phone, *(e["phone"] for e in extra)))
    )
