# ruff: noqa: E501, F811
"""QA T-029 (API): Lịch sử chơi `GET /member-area/play-history?month=` (AC2, AC3, AC4) – dữ liệu tạo bằng luồng phòng chơi thật (bốc → bắt đầu → lưu tỉ số).

Spec `T-029-lich-su-choi.md`: buổi chơi = phòng có ≥ 1 trận `finished` có mình ở đội A/B (kể cả đã rời phòng), tháng theo giờ VN, không tính `abandoned`,
số trận/thắng/thua khớp tab Lịch sử trận đấu của phòng, tháng tương lai rỗng, tháng sai 422, ETag, chỉ dữ liệu của mình.
"""

from datetime import UTC, datetime

from app.core.config import settings
from tests.conftest import API, _rate_limit_backend, idem
from tests.helpers_booking import today
from tests.qa_rooms import act, detail, err, fill, make_room, people, q, tick, x  # noqa: F401

MA = f"{API}/member-area"
ROOMS = f"{MA}/rooms"
HISTORY = f"{MA}/play-history"
M = f"{API}/members"


def this_month() -> str:
    return datetime.now(settings.tz).strftime("%Y-%m")


async def hv(c, rid):
    return (await detail(c, rid))["version"]


async def play(c, rid, a, b):
    d = (await act(c, rid, "/draw", {"version": await hv(c, rid)})).json()
    assert d["current_match"]["status"] == "drawn"
    s = await act(c, rid, "/start", {"version": await hv(c, rid)})
    assert s.status_code == 200, s.text
    no = s.json()["current_match"]["no"]
    r = await act(
        c, rid, f"/matches/{no}/result", {"score_a": a, "score_b": b, "version": await hv(c, rid)}
    )
    assert r.status_code == 200, r.text


async def history(c, month: str | None = None, **headers):
    return await c.get(HISTORY, params={"month": month} if month else {}, headers=headers)


async def room_with_four(admin, people):
    """Host + 3 hội viên có tài khoản, đều vào phòng bằng xin vào/duyệt; trả (host, [p1,p2,p3], room_id, spec)."""
    _rate_limit_backend.clear()
    host = await people("Chủ Lịch Sử")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    others = []
    for i in range(3):
        _rate_limit_backend.clear()
        p = await people(f"Người Chơi {i}")
        others.append(p)
    await fill(rid, host, others)
    return host, others, rid, spec


def oracle(matches: dict) -> dict[str, tuple[int, int]]:
    """{tên: (thắng, thua)} từ Lịch sử trận đấu của phòng."""
    res: dict[str, list[int]] = {}
    for it in matches["items"]:
        win, lose = (
            (it["team_a"], it["team_b"]) if it["winner"] == "a" else (it["team_b"], it["team_a"])
        )
        for p in win:
            res.setdefault(p, [0, 0])[0] += 1
        for p in lose:
            res.setdefault(p, [0, 0])[1] += 1
    return {k: (v[0], v[1]) for k, v in res.items()}


# ============================================================ AC4: khớp tab Lịch sử trận đấu của phòng


async def test_ac4_numbers_equal_each_players_part_of_the_room_history(admin, people):
    host, others, rid, spec = await room_with_four(admin, people)
    for a, b in ((21, 10), (8, 21), (21, 19)):
        await play(host.client, rid, a, b)
    ms = (await host.client.get(f"{ROOMS}/{rid}/matches")).json()
    want = oracle(ms)
    assert ms["total"] == 3 and len(want) == 4
    for who in (host, *others):
        d = (await history(who.client)).json()
        assert d["month"] == this_month()
        [item] = [i for i in d["items"] if i["room_id"] == rid]
        wins, losses = want[who.name]
        assert (item["matches"], item["wins"], item["losses"]) == (3, wins, losses), (
            who.name,
            item,
            want[who.name],
        )
        assert item["matches"] == item["wins"] + item["losses"]
        assert item["resource_name"] == spec["room"]["resource_name"] and item["resource_type_name"]
        assert item["start_at"] and item["end_at"] and item["date"] == today().isoformat()
        assert (
            d["summary"]["wins"] >= wins
            and d["summary"]["matches"] >= 3
            and d["summary"]["sessions"] >= 1
        )
    # chỉ dữ liệu của mình: không có tên / SĐT / id người khác trong phản hồi
    r = await history(host.client)
    for o in others:
        assert o.phone not in r.text and o.name not in r.text
    assert set(r.json()["items"][0]) == {
        "room_id",
        "date",
        "resource_name",
        "resource_type_name",
        "start_at",
        "end_at",
        "matches",
        "wins",
        "losses",
    }
    assert set(r.json()["summary"]) == {"sessions", "matches", "wins"}


async def test_ac2_player_who_left_the_room_still_has_the_session(admin, people):
    host, others, rid, _ = await room_with_four(admin, people)
    await play(host.client, rid, 21, 12)
    leaver = others[0]
    assert (
        await act(leaver.client, rid, "/leave", {"version": await hv(leaver.client, rid)})
    ).status_code == 200
    d = (await history(leaver.client)).json()
    [item] = [i for i in d["items"] if i["room_id"] == rid]
    assert item["matches"] == 1 and item["wins"] + item["losses"] == 1, "rời phòng vẫn giữ kết quả"
    # bị mời ra cũng vậy
    kicked = others[1]
    mid = next(
        m["id"]
        for m in (await detail(host.client, rid))["members"]
        if m["display_name"] == kicked.name
    )
    assert (
        await act(host.client, rid, f"/members/{mid}/kick", {"version": await hv(host.client, rid)})
    ).status_code == 200
    d = (await history(kicked.client)).json()
    assert any(i["room_id"] == rid and i["matches"] == 1 for i in d["items"])


async def test_ac2_abandoned_drawn_playing_and_empty_rooms_do_not_count(admin, people):
    host, _, rid, _ = await room_with_four(admin, people)
    # chỉ có trận bị bỏ dở (đóng phòng khi đang chơi): không thành buổi chơi
    await act(host.client, rid, "/draw", {"version": await hv(host.client, rid)})
    assert (
        await act(host.client, rid, "/start", {"version": await hv(host.client, rid)})
    ).status_code == 200
    d0 = (await history(host.client)).json()
    assert all(i["room_id"] != rid for i in d0["items"]), "trận đang chơi chưa tính"
    await x(
        "UPDATE play_room SET end_at = now() - interval '11 minutes', start_at = now() - interval '71 minutes' WHERE id=:i",
        i=rid,
    )
    await tick()
    assert (await detail(host.client, rid))["status"] == "closed"
    d1 = (await history(host.client)).json()
    assert all(i["room_id"] != rid for i in d1["items"]), (
        "trận abandoned không tính, phòng không có trận đã lưu không hiện"
    )
    assert d1["summary"] == d0["summary"]


async def test_ac2_two_vs_two_both_winners_get_the_win_and_summary_adds_up(admin, people):
    host, others, rid, _ = await room_with_four(admin, people)
    await play(host.client, rid, 21, 5)
    wins = 0
    for who in (host, *others):
        d = (await history(who.client)).json()
        [item] = [i for i in d["items"] if i["room_id"] == rid]
        assert (item["wins"], item["losses"]) in {(1, 0), (0, 1)}
        wins += item["wins"]
    assert wins == 2, "2 vs 2: đúng hai người thắng (cả hai người đội thắng đều có 1 thắng)"


# ============================================================ tháng giờ VN, tương lai, lỗi, ETag, thứ tự


async def test_month_follows_vn_time_future_is_empty_and_bad_months_are_422(
    admin, people, anon, customer
):
    host, others, rid, _ = await room_with_four(admin, people)
    await play(host.client, rid, 21, 10)
    # 28/02/2025 17:30 UTC = 01/03/2025 00:30 giờ VN -> tháng 3
    await x(
        "UPDATE play_room SET start_at = :s, end_at = :e WHERE id=:i",
        s=datetime(2025, 2, 28, 17, 30, tzinfo=UTC),
        e=datetime(2025, 2, 28, 18, 30, tzinfo=UTC),
        i=rid,
    )
    assert any(i["room_id"] == rid for i in (await history(host.client, "2025-03")).json()["items"])
    assert all(i["room_id"] != rid for i in (await history(host.client, "2025-02")).json()["items"])
    # 31/03 17:30 UTC = 01/04 00:30 giờ VN -> tháng 4; 31/03 16:30 UTC = 31/03 23:30 VN -> tháng 3
    await x(
        "UPDATE play_room SET start_at = :s, end_at = :e WHERE id=:i",
        s=datetime(2025, 3, 31, 17, 30, tzinfo=UTC),
        e=datetime(2025, 3, 31, 18, 30, tzinfo=UTC),
        i=rid,
    )
    assert any(i["room_id"] == rid for i in (await history(host.client, "2025-04")).json()["items"])
    assert all(i["room_id"] != rid for i in (await history(host.client, "2025-03")).json()["items"])
    await x(
        "UPDATE play_room SET start_at = :s, end_at = :e WHERE id=:i",
        s=datetime(2025, 3, 31, 16, 30, tzinfo=UTC),
        e=datetime(2025, 3, 31, 17, 30, tzinfo=UTC),
        i=rid,
    )
    assert any(i["room_id"] == rid for i in (await history(host.client, "2025-03")).json()["items"])
    # tương lai: 200 rỗng
    d = (await history(host.client, "2099-12")).json()
    assert d["summary"] == {"sessions": 0, "matches": 0, "wins": 0} and d["items"] == []
    # sai
    for bad in ("2026-1", "abc", "2026-1-01", "202601"):
        assert (await history(host.client, bad)).status_code == 422, bad
    assert (await host.client.get(HISTORY, params={"month": ""})).status_code in (200, 422), (
        "month rỗng: mặc định tháng này hoặc báo lỗi, không 500"
    )
    for bad in ("2026-13", "2026-00"):
        r = await history(host.client, bad)
        assert r.status_code == 422 and err(r)["code"] == "E-001", bad
    # quyền
    assert (await anon.get(HISTORY)).status_code == 401
    r = await customer.get(HISTORY)
    assert r.status_code == 403 and err(r)["code"] == "E-HV-8"


async def test_etag_304_and_changes_after_a_new_saved_match_and_newest_first(admin, people):
    host, others, rid, _ = await room_with_four(admin, people)
    await play(host.client, rid, 21, 10)
    r = await history(host.client)
    etag = r.headers["etag"]
    assert "no-cache" in r.headers["cache-control"] and "private" in r.headers["cache-control"]
    assert (await history(host.client, **{"If-None-Match": etag})).status_code == 304
    await play(host.client, rid, 15, 21)
    r2 = await history(host.client, **{"If-None-Match": etag})
    assert r2.status_code == 200 and r2.headers["etag"] != etag
    assert [i for i in r2.json()["items"] if i["room_id"] == rid][0]["matches"] == 2
    other = await history(others[0].client, **{"If-None-Match": etag})
    assert other.status_code == 200, "ETag của người khác không cho 304"
    # thứ tự: phòng mới hơn nằm trên
    spec2 = await make_room(admin, host.client, host.code)
    rid2 = spec2["room"]["id"]
    await x(
        "INSERT INTO play_room_member (room_id, customer_id, queue_state, waiting_since, joined_at) SELECT :r, customer_id, 'waiting', now(), now() FROM play_room_member WHERE room_id=:o AND customer_id <> (SELECT host_customer_id FROM play_room WHERE id=:o)",
        r=rid2,
        o=rid,
    )
    await play(host.client, rid2, 21, 4)
    await x(
        "UPDATE play_room SET start_at = start_at + interval '2 hours', end_at = end_at + interval '2 hours' WHERE id=:i",
        i=rid2,
    )
    items = (await history(host.client)).json()["items"]
    ids = [i["room_id"] for i in items]
    assert ids.index(rid2) < ids.index(rid), "mới nhất trên cùng"
    starts = [i["start_at"] for i in items]
    assert starts == sorted(starts, reverse=True)


# ============================================================ AC3: phòng đã ẩn vẫn có dòng lịch sử


async def test_ac3_hidden_room_row_stays_but_the_room_returns_404(admin, people):
    host, others, rid, _ = await room_with_four(admin, people)
    await play(host.client, rid, 21, 10)
    cur = (await admin.get(f"{M}/{host.code}")).json()
    assert (
        await admin.patch(
            f"{M}/{host.code}", json={"is_active": False, "version": cur["version"]}, headers=idem()
        )
    ).status_code == 200
    d = (await history(others[0].client)).json()
    assert any(i["room_id"] == rid for i in d["items"]), "dòng vẫn nằm trong lịch sử"
    assert (await others[0].client.get(f"{ROOMS}/{rid}")).status_code == 404, (
        "phòng của Host Ngừng bị ẩn (FE báo 'Phòng này không còn xem được')"
    )
    cur = (await admin.get(f"{M}/{host.code}")).json()
    await admin.patch(
        f"{M}/{host.code}", json={"is_active": True, "version": cur["version"]}, headers=idem()
    )
