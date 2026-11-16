# ruff: noqa: E501, F811
"""QA T-027 (API): Host tự xếp đội hình `PUT /member-area/rooms/{id}/lineup` (AC4–AC8) – viết từ spec, độc lập với test BE.

Host đăng nhập (đăng ký OTP); người chơi khác là hội viên do quầy tạo, được đưa vào phòng bằng SQL (không chạm giới hạn đăng ký/IP).
Giao diện (ô đội hình, kéo thả, menu, 360 px: AC1–AC3) kiểm riêng khi có FE.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import delete

from app.core.db import SessionLocal
from app.modules.auth.models import User
from app.modules.members.models import Customer
from tests.conftest import API, idem, unique_phone
from tests.qa_rooms import ROOMS, act, detail, err, fill, make_room, people, q, tick, x  # noqa: F401

M = f"{API}/members"


@pytest.fixture
async def seats():
    """``await seats(admin, room_id, n)`` -> n hội viên do quầy tạo, đã ngồi trong Hàng chờ; dọn khi xong."""
    phones: list[str] = []

    async def seat(admin, room_id: int, n: int) -> list[dict]:
        out = []
        for i in range(n):
            phone = unique_phone()
            phones.append(phone)
            name = f"QAL {uuid.uuid4().hex[:5]} {i}"
            r = await admin.post(M, json={"full_name": name, "phone": phone}, headers=idem())
            assert r.status_code == 201, r.text
            cid = (await q("SELECT id FROM customer WHERE phone=:p", p=phone))[0]["id"]
            await x(
                "INSERT INTO play_room_member (room_id, customer_id, queue_state, waiting_since, joined_at) VALUES (:r, :c, 'waiting', now() - make_interval(secs => :s), now())",
                r=room_id,
                c=cid,
                s=60 * (n - i),
            )
            out.append({"cid": cid, "name": name, "phone": phone})
        return out

    yield seat
    async with SessionLocal() as s:
        await s.execute(delete(Customer).where(Customer.phone.in_(phones)))
        await s.execute(delete(User).where(User.phone.in_(phones)))
        await s.commit()


async def room_of(admin, people, seats, n_extra: int):
    host = await people("Chủ Xếp Đội")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    extra = await seats(admin, rid, n_extra)
    d = await detail(host.client, rid)
    return host, rid, extra, d


def mids(d: dict) -> list[int]:
    return [m["id"] for m in d["members"]]


def team_ids(d: dict, side: str) -> list[int]:
    return [p["member_id"] for p in d["current_match"][side]]


async def lineup(c, rid: int, a: list[int], b: list[int], version: int | None = None, key=None):
    if version is None:
        version = (await detail(c, rid))["version"]
    return await c.put(
        f"{ROOMS}/{rid}/lineup",
        json={"team_a": a, "team_b": b, "version": version},
        headers=key or idem(),
    )


async def fmt(c, rid: int, f: str):
    v = (await detail(c, rid))["version"]
    return await c.put(f"{ROOMS}/{rid}/format", json={"format": f, "version": v}, headers=idem())


async def v(c, rid: int) -> int:
    return (await detail(c, rid))["version"]


# ============================================================ E-ROOM-12 (đội hình không hợp lệ)


async def test_e_room_12_wrong_counts_duplicates_and_strangers_2v2(admin, people, seats):
    host, rid, _, d = await room_of(admin, people, seats, 5)
    m = mids(d)
    bad = {
        "thiếu người ở đội B": ([m[0], m[1]], [m[2]]),
        "đội A chỉ 1 người": ([m[0]], [m[1], m[2]]),
        "cả hai đội rỗng": ([], []),
        "trùng người giữa hai đội": ([m[0], m[1]], [m[1], m[2]]),
        "trùng người trong một đội": ([m[0], m[0]], [m[1], m[2]]),
        "id không ở phòng": ([m[0], m[1]], [m[2], 999_999_999]),
        "id âm / 0": ([m[0], 0], [m[1], m[2]]),
    }
    for label, (a, b) in bad.items():
        r = await lineup(host.client, rid, a, b)
        assert (
            r.status_code == 422
            and err(r)["code"] == "E-ROOM-12"
            and err(r)["message"] == "Đội hình không hợp lệ."
        ), (label, r.status_code, r.text[:120])
    # hơn 2 người một đội: lỗi kiểm dữ liệu (422), cũng không lưu
    r = await lineup(host.client, rid, [m[0], m[1], m[2]], [m[3], m[4]])
    assert r.status_code == 422
    assert (await detail(host.client, rid))["current_match"] is None, (
        "đội hình sai không để lại trận"
    )


async def test_e_room_12_member_of_another_room_is_a_stranger(admin, people, seats):
    host, rid, _, d = await room_of(admin, people, seats, 4)
    other = await people("Chủ Phòng Khác")
    spec = await make_room(admin, other.client, other.code)
    foreign = await seats(admin, spec["room"]["id"], 2)
    fm = [
        mm["id"]
        for mm in (await detail(other.client, spec["room"]["id"]))["members"]
        if mm["display_name"] in {f["name"] for f in foreign}
    ]
    assert len(fm) == 2
    m = mids(d)
    r = await lineup(host.client, rid, [m[0], fm[0]], [m[1], fm[1]])
    assert r.status_code == 422 and err(r)["code"] == "E-ROOM-12", (
        "dòng thành viên của phòng khác không dùng được"
    )


async def test_e_room_12_counts_follow_the_format_1v1(admin, people, seats):
    host, rid, _, d = await room_of(admin, people, seats, 3)
    m = mids(d)
    assert (await fmt(host.client, rid, "1v1")).status_code == 200
    for a, b in (([m[0], m[1]], [m[2]]), ([m[0]], []), ([m[0], m[1]], [m[2], m[3]])):
        r = await lineup(host.client, rid, a, b)
        assert r.status_code == 422, (a, b)
    r = await lineup(host.client, rid, [m[0]], [m[1]])
    assert r.status_code == 200, r.text
    cm = r.json()["current_match"]
    assert cm["format"] == "1v1" and len(cm["team_a"]) == len(cm["team_b"]) == 1
    # 2v2 với 1+1 → sai
    assert (await fmt(host.client, rid, "2v2")).status_code == 200
    assert (await detail(host.client, rid))["current_match"] is None, "đổi thể thức xóa đội hình"
    r = await lineup(host.client, rid, [m[0]], [m[1]])
    assert r.status_code == 422 and err(r)["code"] == "E-ROOM-12"


# ============================================================ quyền, version, key, đóng phòng, đang chơi


async def test_only_the_host_can_set_the_lineup(admin, people, seats, anon):
    host, rid, _, d = await room_of(admin, people, seats, 3)
    member = await people("Thành Viên Thường")
    outsider = await people("Người Ngoài")
    await fill(rid, host, [member])
    d = await detail(host.client, rid)
    m = mids(d)
    for who in (member, outsider):
        r = await lineup(who.client, rid, [m[0], m[1]], [m[2], m[3]], await v(who.client, rid))
        assert r.status_code == 403 and err(r)["code"] == "E-ROOM-7", who.name
    r = await anon.put(
        f"{ROOMS}/{rid}/lineup",
        json={"team_a": [m[0], m[1]], "team_b": [m[2], m[3]], "version": 1},
        headers=idem(),
    )
    assert r.status_code == 401
    assert (await lineup(host.client, 999_999, [1, 2], [3, 4], 1)).status_code == 404
    assert (await detail(host.client, rid))["current_match"] is None, (
        "người không phải Host không tạo được đội hình"
    )


async def test_stale_version_missing_key_and_bad_origin(admin, people, seats):
    host, rid, _, d = await room_of(admin, people, seats, 4)
    m = mids(d)
    old = d["version"]
    assert (
        await act(host.client, rid, "/draw", {"version": old})
    ).status_code == 200  # version tăng
    r = await lineup(host.client, rid, [m[0], m[1]], [m[2], m[3]], old)
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-6"
    cur = await v(host.client, rid)
    r = await host.client.put(
        f"{ROOMS}/{rid}/lineup",
        json={"team_a": [m[0], m[1]], "team_b": [m[2], m[3]], "version": cur},
    )
    assert r.status_code == 400 and err(r)["code"] == "E-SEC-2", "thiếu Idempotency-Key"
    r = await host.client.put(
        f"{ROOMS}/{rid}/lineup",
        json={"team_a": [m[0], m[1]], "team_b": [m[2], m[3]], "version": cur},
        headers={**idem(), "Origin": "https://evil.example"},
    )
    assert r.status_code == 403 and err(r)["code"] == "E-SEC-1"
    for bad in (
        {"team_a": [m[0], m[1]]},
        {"team_a": "x", "team_b": [], "version": cur},
        {"team_a": [m[0], m[1]], "team_b": [m[2], m[3]], "version": cur, "extra": 1},
    ):
        r = await host.client.put(f"{ROOMS}/{rid}/lineup", json=bad, headers=idem())
        assert r.status_code == 422, bad


async def test_closed_room_and_playing_match_block_the_lineup(admin, people, seats):
    host, rid, _, d = await room_of(admin, people, seats, 4)
    m = mids(d)
    assert (await lineup(host.client, rid, [m[0], m[1]], [m[2], m[3]])).status_code == 200
    assert (
        await act(host.client, rid, "/start", {"version": await v(host.client, rid)})
    ).status_code == 200
    r = await lineup(host.client, rid, [m[0], m[2]], [m[1], m[3]])
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-11" and err(r).get("match_no") == 1, (
        "trận đang chơi: sân khóa"
    )
    cm = (await detail(host.client, rid))["current_match"]
    assert cm["status"] == "playing" and team_ids({"current_match": cm}, "team_a") == [
        m[0],
        m[1],
    ], "đội hình đang chơi không đổi"
    # đóng phòng → E-ROOM-1
    await x(
        "UPDATE play_room SET end_at = now() - interval '11 minutes', start_at = now() - interval '71 minutes' WHERE id=:i",
        i=rid,
    )
    await tick()
    r = await lineup(host.client, rid, [m[0], m[1]], [m[2], m[3]])
    assert r.status_code == 409 and err(r)["code"] == "E-ROOM-1"


# ============================================================ luồng chính + AC4, AC6, AC7, AC8


async def test_lineup_start_result_flows_into_history_and_ranking_without_touching_waiting_since(
    admin, people, seats
):
    host, rid, extra, d = await room_of(admin, people, seats, 5)  # 6 người
    m = mids(d)
    before = {mm["id"]: mm["waiting_since"] for mm in d["members"]}
    a, b = [m[1], m[4]], [m[2], m[5]]  # Host (m[0]) và m[3] ngồi chờ: Host cố ý không vào đội
    r = await lineup(host.client, rid, a, b)
    assert r.status_code == 200, r.text
    d2 = r.json()
    assert (d2["current_match"]["no"], d2["current_match"]["status"]) == (1, "drawn")
    assert team_ids(d2, "team_a") == a and team_ids(d2, "team_b") == b, "đúng thứ tự Host xếp"
    assert {mm["id"]: mm["waiting_since"] for mm in d2["members"]} == before, (
        "AC8: xếp tay không đổi waiting_since của ai"
    )
    assert all(mm["queue_state"] == "waiting" for mm in d2["members"])
    # bắt đầu → đúng 4 người sang Đang chơi
    s = await act(host.client, rid, "/start", {"version": d2["version"]})
    assert s.status_code == 200, s.text
    playing = {mm["id"] for mm in s.json()["members"] if mm["queue_state"] == "playing"}
    assert playing == set(a + b), "chỉ 4 người trong đội hình sang Đang chơi"
    # lưu kết quả → Lịch sử + Xếp hạng
    names = {mm["id"]: mm["display_name"] for mm in s.json()["members"]}
    res = await act(
        host.client,
        rid,
        "/matches/1/result",
        {"score_a": 21, "score_b": 17, "version": s.json()["version"]},
    )
    assert res.status_code == 200, res.text
    hist = (await host.client.get(f"{ROOMS}/{rid}/matches")).json()
    row = hist["items"][0]
    assert row["no"] == 1 and (row["score_a"], row["score_b"], row["winner"]) == (21, 17, "a")
    assert sorted(row["team_a"]) == sorted(names[i] for i in a) and sorted(row["team_b"]) == sorted(
        names[i] for i in b
    )
    rank = (await host.client.get(f"{ROOMS}/{rid}/ranking")).json()["items"]
    wins = {r["display_name"]: r["wins"] for r in rank}
    assert {names[i] for i in a} == {n for n, w in wins.items() if w == 1} and {
        names[i] for i in b
    } == {n for n, w in wins.items() if w == 0}
    # người đã đánh về cuối Hàng chờ; hai người chưa đánh giữ nguyên mốc
    after = {mm["id"]: mm["waiting_since"] for mm in res.json()["members"]}
    for i in (m[0], m[3]):
        assert after[i] == before[i], "người không đánh giữ waiting_since"
    assert min(after[i] for i in a + b) > max(before.values()), "người vừa đánh vào cuối Hàng chờ"


async def test_relineup_keeps_match_number_and_draw_replaces_the_whole_field(admin, people, seats):
    host, rid, _, d = await room_of(admin, people, seats, 5)
    m = mids(d)
    r1 = await lineup(host.client, rid, [m[0], m[1]], [m[2], m[3]])
    r2 = await lineup(host.client, rid, [m[3], m[4]], [m[5], m[0]])
    assert r1.json()["current_match"]["no"] == r2.json()["current_match"]["no"] == 1, (
        "xếp lại giữ số trận"
    )
    assert team_ids(r2.json(), "team_a") == [m[3], m[4]]
    assert len(await q("SELECT 1 FROM play_match WHERE room_id=:i", i=rid)) == 1, (
        "không sinh trận thừa"
    )
    dr = await act(host.client, rid, "/draw", {"version": r2.json()["version"]})
    assert dr.status_code == 200
    cm = dr.json()["current_match"]
    assert (
        cm["no"] == 1 and cm["status"] == "drawn" and len(cm["team_a"]) == len(cm["team_b"]) == 2
    ), "AC4: bốc điền lại cả sân"
    # sau khi bốc vẫn xếp tay chỉnh lại được
    again = await lineup(host.client, rid, [m[0], m[1]], [m[2], m[3]], dr.json()["version"])
    assert again.status_code == 200 and team_ids(again.json(), "team_b") == [m[2], m[3]]


async def test_ac6_ac7_start_time_rule_and_everyone_sees_the_saved_lineup_only(
    admin, people, seats
):
    host, rid, _, d = await room_of(admin, people, seats, 4)
    guest = await people("Người Xem Đội Hình")
    await fill(rid, host, [guest])
    d = await detail(host.client, rid)
    m = mids(d)
    assert (await detail(guest.client, rid))["current_match"] is None
    r = await lineup(host.client, rid, [m[0], m[1]], [m[2], m[3]])
    assert r.status_code == 200
    seen = (await detail(guest.client, rid))["current_match"]
    assert seen["status"] == "drawn" and [p["member_id"] for p in seen["team_a"]] == [m[0], m[1]], (
        "thành viên khác thấy đội hình đã lưu"
    )
    outsider = await people("Người Ngoài Đội Hình")
    assert (await detail(outsider.client, rid))["current_match"]["status"] == "drawn", (
        "người ngoài phòng cũng xem được"
    )
    assert "phone" not in str(seen) and host.phone not in str(seen)
    # AC6: vẫn chịu luật 15 phút trước giờ chơi
    await x(
        "UPDATE play_room SET start_at = now() + interval '16 minutes', end_at = now() + interval '76 minutes' WHERE id=:i",
        i=rid,
    )
    s = await act(host.client, rid, "/start", {"version": await v(host.client, rid)})
    assert s.status_code == 409 and err(s)["code"] == "E-ROOM-10"
    await x("UPDATE play_room SET start_at = now() + interval '14 minutes' WHERE id=:i", i=rid)
    assert (
        await act(host.client, rid, "/start", {"version": await v(host.client, rid)})
    ).status_code == 200


# ============================================================ AC8: xóa đội hình khi người rời / bị mời ra / đổi thể thức


async def test_ac8_a_drawn_player_leaving_or_kicked_clears_the_lineup_but_others_do_not(
    admin, people, seats
):
    host, rid, extra, d = await room_of(admin, people, seats, 5)
    m = mids(d)
    assert (await lineup(host.client, rid, [m[0], m[1]], [m[2], m[3]])).status_code == 200
    # người không nằm trong đội hình bị mời ra → đội hình giữ
    bystander = m[4]
    k = await act(
        host.client, rid, f"/members/{bystander}/kick", {"version": await v(host.client, rid)}
    )
    assert k.status_code == 200 and k.json()["current_match"] is not None
    # người trong đội hình bị mời ra → đội hình bị xóa
    k = await act(host.client, rid, f"/members/{m[3]}/kick", {"version": await v(host.client, rid)})
    assert k.status_code == 200 and k.json()["current_match"] is None
    assert not await q("SELECT 1 FROM play_match WHERE room_id=:i AND status='drawn'", i=rid)
    # người trong đội hình tự rời → xóa
    assert (await lineup(host.client, rid, [m[0], m[1]], [m[2], m[5]])).status_code == 200
    guest = await people("Người Rời Đội Hình")
    await fill(rid, host, [guest])
    gm = next(
        mm["id"]
        for mm in (await detail(host.client, rid))["members"]
        if mm["is_me"] is False and mm["display_name"] == guest.name
    )
    assert (await lineup(host.client, rid, [m[0], m[1]], [m[2], gm])).status_code == 200
    left = await act(guest.client, rid, "/leave", {"version": await v(guest.client, rid)})
    assert left.status_code == 200
    assert (await detail(host.client, rid))["current_match"] is None, (
        "người được xếp rời phòng → bỏ đội hình"
    )


async def test_ac8_format_change_clears_lineup_and_double_submit_is_idempotent(
    admin, people, seats
):
    host, rid, _, d = await room_of(admin, people, seats, 4)
    m = mids(d)
    key = idem()
    version = d["version"]
    r1 = await lineup(host.client, rid, [m[0], m[1]], [m[2], m[3]], version, key)
    r2 = await lineup(host.client, rid, [m[0], m[1]], [m[2], m[3]], version, key)
    assert (
        r1.status_code == r2.status_code == 200
        and r2.json() == r1.json()
        and r2.headers.get("idempotent-replayed") == "true"
    )
    assert len(await q("SELECT 1 FROM play_match WHERE room_id=:i", i=rid)) == 1
    assert (await fmt(host.client, rid, "1v1")).json()["current_match"] is None


async def test_concurrent_lineups_with_one_version_apply_exactly_one(admin, people, seats):
    host, rid, _, d = await room_of(admin, people, seats, 5)
    m = mids(d)
    version = d["version"]
    combos = [
        ([m[0], m[1]], [m[2], m[3]]),
        ([m[1], m[2]], [m[3], m[4]]),
        ([m[4], m[5]], [m[0], m[1]]),
    ]
    res = await asyncio.gather(*[lineup(host.client, rid, a, b, version) for a, b in combos])
    assert sorted(r.status_code for r in res) == [200, 409, 409], [r.status_code for r in res]
    assert all(err(r)["code"] == "E-ROOM-6" for r in res if r.status_code == 409)
    won = next(c for c, r in zip(combos, res, strict=True) if r.status_code == 200)
    cm = (await detail(host.client, rid))["current_match"]
    assert [p["member_id"] for p in cm["team_a"]] == won[0] and [
        p["member_id"] for p in cm["team_b"]
    ] == won[1]
    assert len(await q("SELECT 1 FROM play_match WHERE room_id=:i", i=rid)) == 1


# ============================================================ nhật ký


async def test_audit_room_lineup_set_has_teams_and_no_phone(admin, people, seats):
    host, rid, extra, d = await room_of(admin, people, seats, 4)
    m = mids(d)
    base = (await q("SELECT coalesce(max(id),0) AS m FROM audit_log"))[0]["m"]
    assert (await lineup(host.client, rid, [m[0], m[1]], [m[2], m[3]])).status_code == 200
    rows = await q(
        "SELECT actor_type, entity_code, detail::text AS d FROM audit_log WHERE action='room.lineup_set' AND id > :b",
        b=base,
    )
    assert (
        len(rows) == 1
        and rows[0]["actor_type"] == "customer"
        and rows[0]["entity_code"] == str(rid)
    )
    dtl = rows[0]["d"]
    assert "Đội A" in dtl and "Đội B" in dtl
    for ph in (host.phone, *(e["phone"] for e in extra)):
        assert ph not in dtl and ph[1:] not in dtl, "không SĐT trong nhật ký đội hình"
    # lỗi không ghi nhật ký
    base2 = (await q("SELECT coalesce(max(id),0) AS m FROM audit_log"))[0]["m"]
    assert (await lineup(host.client, rid, [m[0]], [m[1], m[2]])).status_code == 422
    assert not await q(
        "SELECT 1 FROM audit_log WHERE action='room.lineup_set' AND id > :b", b=base2
    )
