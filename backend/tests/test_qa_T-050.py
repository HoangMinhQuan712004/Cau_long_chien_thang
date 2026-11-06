# ruff: noqa: E501, F811
"""QA T-050 AC2 (backend thật, không thêm API / quyền): popup Lịch sử chơi dùng đúng hai GET của phòng –
``/rooms/{id}/matches`` và ``/rooms/{id}/ranking`` – nên người đã rời phòng / bị mời ra phải xem được như trước,
và số liệu phải khớp dòng trong ``/play-history``. Phòng của Host Ngừng bị ẩn (404) -> popup phải báo lỗi (kiểm ở UI).
"""

from datetime import datetime

from app.core.config import settings
from tests.conftest import API, _rate_limit_backend, idem
from tests.qa_rooms import act, detail, fill, make_room, people  # noqa: F401

MA = f"{API}/member-area"
ROOMS = f"{MA}/rooms"
HISTORY = f"{MA}/play-history"
M = f"{API}/members"


async def ver(c, rid) -> int:
    return (await detail(c, rid))["version"]


async def play(c, rid, a, b):
    d = (await act(c, rid, "/draw", {"version": await ver(c, rid)})).json()
    assert d["current_match"]["status"] == "drawn"
    s = await act(c, rid, "/start", {"version": await ver(c, rid)})
    assert s.status_code == 200, s.text
    no = s.json()["current_match"]["no"]
    r = await act(
        c, rid, f"/matches/{no}/result", {"score_a": a, "score_b": b, "version": await ver(c, rid)}
    )
    assert r.status_code == 200, r.text


async def room_with_four(admin, people):
    _rate_limit_backend.clear()
    host = await people("Chủ Popup")
    spec = await make_room(admin, host.client, host.code)
    rid = spec["room"]["id"]
    others = []
    for i in range(3):
        _rate_limit_backend.clear()
        others.append(await people(f"Người Popup {i}"))
    await fill(rid, host, others)
    return host, others, rid


async def popup_data(c, rid):
    """Đúng hai lời gọi RoomHistory làm khi mở popup (mặc định chưa chọn thể thức)."""
    m = await c.get(f"{ROOMS}/{rid}/matches")
    r = await c.get(f"{ROOMS}/{rid}/ranking")
    return m, r


async def history_item(c, rid) -> dict:
    month = datetime.now(settings.tz).strftime("%Y-%m")
    items = (await c.get(HISTORY, params={"month": month})).json()["items"]
    return next(i for i in items if i["room_id"] == rid)


async def test_ac2_left_and_kicked_players_open_the_popup_data_and_numbers_match(admin, people):
    host, others, rid = await room_with_four(admin, people)
    await play(host.client, rid, 21, 12)
    await play(host.client, rid, 15, 21)
    before = {}
    for p in (host, *others):
        m, r = await popup_data(p.client, rid)
        assert m.status_code == 200 and r.status_code == 200, (m.text, r.text)
        before[p.name] = (m.json(), r.json())

    leaver, kicked, stayer = others
    assert (
        await act(leaver.client, rid, "/leave", {"version": await ver(leaver.client, rid)})
    ).status_code == 200
    mid = next(
        mm["id"]
        for mm in (await detail(host.client, rid))["members"]
        if mm["display_name"] == kicked.name
    )
    assert (
        await act(
            host.client, rid, f"/members/{mid}/kick", {"version": await ver(host.client, rid)}
        )
    ).status_code == 200

    for p in (leaver, kicked):  # đã không còn trong phòng
        assert (await detail(host.client, rid))["members"], "phòng còn"
        m, r = await popup_data(p.client, rid)
        assert m.status_code == 200 and r.status_code == 200, (p.name, m.status_code, m.text)
        mj, rj = m.json(), r.json()
        assert (mj["total"], mj["count_2v2"], mj["count_1v1"]) == (2, 2, 0), (
            "số liệu giữ nguyên sau khi rời"
        )
        assert [(i["no"], i["score_a"], i["score_b"]) for i in mj["items"]] == [
            (i["no"], i["score_a"], i["score_b"]) for i in before[p.name][0]["items"]
        ]
        assert rj["items"] == before[p.name][1]["items"], (
            "bảng xếp hạng phòng vẫn đủ, người rời vẫn giữ kết quả"
        )
        # popup khớp dòng trong Lịch sử chơi của chính người đó
        row = await history_item(p.client, rid)
        assert row["matches"] == mj["total"]
        mine = next(i for i in rj["items"] if i["display_name"] == p.name)
        assert (row["wins"], row["losses"]) == (mine["wins"], mine["losses"])
    # Người còn lại thấy cùng danh sách trận
    m, _ = await popup_data(stayer.client, rid)
    assert m.json()["total"] == 2
    # lọc thể thức khớp: chỉ 2v2
    f = await leaver.client.get(f"{ROOMS}/{rid}/matches", params={"format": "2v2"})
    assert f.status_code == 200 and f.json()["total"] == 2 and len(f.json()["items"]) == 2
    f = await leaver.client.get(f"{ROOMS}/{rid}/matches", params={"format": "1v1"})
    assert f.status_code == 200 and f.json()["items"] == []


async def test_ac2_popup_requests_are_read_only_and_need_login(admin, anon, people):
    host, others, rid = await room_with_four(admin, people)
    await play(host.client, rid, 21, 18)
    for path in ("matches", "ranking"):
        assert (await anon.get(f"{ROOMS}/{rid}/{path}")).status_code == 401
    # Phòng không có thật / số sai -> không 500
    for rid_bad in (99999999, 0):
        m = await others[0].client.get(f"{ROOMS}/{rid_bad}/matches")
        assert m.status_code in (404, 422), m.status_code
    # ETag: popup mở lại với If-None-Match -> 304 hoặc 200, không lỗi
    m = await others[0].client.get(f"{ROOMS}/{rid}/matches")
    tag = m.headers.get("etag")
    assert tag
    again = await others[0].client.get(f"{ROOMS}/{rid}/matches", headers={"If-None-Match": tag})
    assert again.status_code in (200, 304)


async def test_ac2_room_of_deactivated_host_is_hidden_for_popup_but_row_stays(admin, people):
    """Phòng của Host Ngừng: dòng vẫn trong Lịch sử chơi, nhưng matches / ranking trả 404 -> popup phải báo lỗi rõ."""
    host, others, rid = await room_with_four(admin, people)
    await play(host.client, rid, 21, 10)
    cur = (await admin.get(f"{M}/{host.code}")).json()
    assert (
        await admin.patch(
            f"{M}/{host.code}", json={"is_active": False, "version": cur["version"]}, headers=idem()
        )
    ).status_code == 200
    try:
        assert (await history_item(others[0].client, rid))["matches"] == 1
        m, r = await popup_data(others[0].client, rid)
        assert (m.status_code, r.status_code) == (404, 404)
    finally:
        cur = (await admin.get(f"{M}/{host.code}")).json()
        await admin.patch(
            f"{M}/{host.code}", json={"is_active": True, "version": cur["version"]}, headers=idem()
        )
    m, r = await popup_data(others[0].client, rid)
    assert (m.status_code, r.status_code) == (200, 200), "Host hoạt động lại -> xem được"
