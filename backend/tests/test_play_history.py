"""T-029: Lịch sử chơi của hội viên theo tháng (dữ liệu phòng chơi T-017)."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.play_rooms import api as rooms
from app.modules.play_rooms.models import PlayMatch, PlayRoom
from tests import test_play_rooms as base
from tests.test_play_rooms import MA, room_for

people = base.people  # fixture dùng chung (hội viên có tài khoản liên kết)

HISTORY = f"{MA}/play-history"


async def add_match(room_id: int, no: int, a: list[int], b: list[int], status="finished", win="a"):
    now = datetime.now(UTC)
    async with SessionLocal() as s:
        s.add(
            PlayMatch(
                room_id=room_id,
                no=no,
                format="2v2" if len(a) == 2 else "1v1",
                team_a=a,
                team_b=b,
                names={},
                status=status,
                started_at=now,
                ended_at=now if status == "finished" else None,
                score_a=21 if status == "finished" and win == "a" else 15,
                score_b=15 if status == "finished" and win == "a" else 21,
                winner=win if status == "finished" else None,
            )
        )
        await s.commit()


async def history(client, month: str | None = None, **headers):
    params = {"month": month} if month else {}
    return await client.get(HISTORY, params=params, headers=headers)


def this_month() -> str:
    return datetime.now(settings.tz).strftime("%Y-%m")


async def test_play_history_counts_sessions_matches_wins(staff, admin, people):
    host = await people("Người Chơi")
    left = await people("Đã Rời Phòng")  # có tên trong trận nhưng không còn là thành viên phòng
    h, x = host.customer_id, left.customer_id
    room = (await room_for(staff, admin, host.code))["room"]
    await add_match(room.id, 1, [h, x], [-1, -2], win="a")  # 2 vs 2: cả hai người đội A thắng
    await add_match(room.id, 2, [-1, -2], [h, -3], win="a")  # mình thua
    await add_match(room.id, 3, [h], [-1], status="abandoned")  # không tính
    await add_match(room.id, 4, [-1], [-2], win="b")  # không có mình
    empty = (await room_for(staff, admin, host.code))["room"]  # phòng chưa có trận đã lưu
    await add_match(empty.id, 1, [h], [-1], status="abandoned")

    r = await history(host.client)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-cache, private" and r.headers["etag"]
    d = r.json()
    assert d["month"] == this_month()
    assert d["summary"] == {"sessions": 1, "matches": 2, "wins": 1}
    [item] = d["items"]
    assert item["room_id"] == room.id and (item["matches"], item["wins"], item["losses"]) == (
        2,
        1,
        1,
    )
    assert item["resource_name"] == room.resource_name
    assert item["resource_type_name"] == room.resource_type_name
    assert item["date"] == room.start_at.astimezone(settings.tz).date().isoformat()

    # Không còn ở phòng vẫn tính (T-017 AC20)
    d = (await history(left.client)).json()
    assert d["summary"] == {"sessions": 1, "matches": 1, "wins": 1}

    # ETag: không đổi -> 304
    again = await history(host.client, **{"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304


async def test_month_boundary_vn_time_future_and_errors(anon, customer, staff, admin, people):
    host = await people()
    h = host.customer_id
    early = (await room_for(staff, admin, host.code))["room"]
    late = (await room_for(staff, admin, host.code))["room"]
    for room in (early, late):
        await add_match(room.id, 1, [h], [-1])
    async with SessionLocal() as s:
        # 28/02/2025 17:30 UTC = 01/03 00:30 giờ VN -> tháng 3
        t = datetime(2025, 2, 28, 17, 30, tzinfo=UTC)
        await s.execute(
            update(PlayRoom)
            .where(PlayRoom.id == early.id)
            .values(start_at=t, end_at=t + timedelta(hours=1))
        )
        # 31/03/2025 17:00 UTC = 01/04 00:00 giờ VN -> tháng 4
        t = datetime(2025, 3, 31, 17, 0, tzinfo=UTC)
        await s.execute(
            update(PlayRoom)
            .where(PlayRoom.id == late.id)
            .values(start_at=t, end_at=t + timedelta(hours=1))
        )
        await s.commit()

    feb, mar, apr = [
        (await history(host.client, m)).json() for m in ("2025-02", "2025-03", "2025-04")
    ]
    assert feb["items"] == []
    assert [i["room_id"] for i in mar["items"]] == [early.id]
    assert mar["items"][0]["date"] == "2025-03-01"
    assert [i["room_id"] for i in apr["items"]] == [late.id]

    # Tháng tương lai -> rỗng (không lỗi)
    future = (datetime.now(settings.tz) + timedelta(days=40)).strftime("%Y-%m")
    d = (await history(host.client, future)).json()
    assert d["month"] == future and d["start"] == f"{future}-01" and d["items"] == []
    assert d["summary"] == {"sessions": 0, "matches": 0, "wins": 0}

    for bad in ("2026-13", "2026-00", "2026-1", "abc"):
        assert (await history(host.client, bad)).status_code == 422, bad
    assert (await history(anon)).status_code == 401
    r = await history(customer)
    assert r.status_code == 403 and r.json()["detail"]["code"] == "E-HV-8"


async def test_date_range_spans_months_vn_time_and_errors(staff, admin, people):
    """Khoảng Từ–Đến chọn tự do (qua nhiều tháng), gồm cả 2 đầu theo giờ VN; sai -> 422 E-001."""
    host = await people()
    h = host.customer_id
    early = (await room_for(staff, admin, host.code))["room"]
    late = (await room_for(staff, admin, host.code))["room"]
    for room in (early, late):
        await add_match(room.id, 1, [h], [-1])
    async with SessionLocal() as s:
        for room, t in (
            (early, datetime(2025, 2, 28, 17, 30, tzinfo=UTC)),  # 01/03/2025 00:30 VN
            (late, datetime(2025, 4, 10, 16, 59, tzinfo=UTC)),  # 10/04/2025 23:59 VN
        ):
            await s.execute(
                update(PlayRoom)
                .where(PlayRoom.id == room.id)
                .values(start_at=t, end_at=t + timedelta(hours=1))
            )
        await s.commit()

    async def span(**params):
        return await host.client.get(HISTORY, params=params)

    d = (await span(**{"from": "2025-03-01", "to": "2025-04-10", "month": "2024-01"})).json()
    assert [i["room_id"] for i in d["items"]] == [late.id, early.id]  # có range thì bỏ qua month
    assert (d["start"], d["end"], d["month"]) == ("2025-03-01", "2025-04-10", "2025-03")
    assert d["summary"] == {"sessions": 2, "matches": 2, "wins": 2}
    d = (await span(**{"from": "2025-03-02", "to": "2025-04-09"})).json()
    assert d["items"] == []  # hai đầu khoảng theo ngày giờ VN
    d = (await span(**{"from": "2025-04-10", "to": "2025-04-10"})).json()
    assert [i["room_id"] for i in d["items"]] == [late.id]

    for params, message in (
        ({"from": "2025-03-01"}, "Vui lòng chọn cả Từ ngày và Đến ngày."),
        ({"from": "2025-04-02", "to": "2025-04-01"}, "Từ ngày phải trước hoặc bằng Đến ngày."),
        ({"from": "2024-01-01", "to": "2025-01-01"}, "Khoảng ngày tối đa 1 năm."),
    ):
        r = await span(**params)
        assert r.status_code == 422, params
        assert r.json()["detail"] == {"code": "E-001", "message": message}
    assert (await span(**{"from": "2025-02-30", "to": "2025-03-01"})).status_code == 422


async def test_career_stats_for_record_card(staff, admin, people):
    """Thẻ kỷ lục: tổng thắng / thua mọi thời gian (mọi phòng), cùng cách đếm Lịch sử chơi."""
    host, mate = await people("Phá Kỷ Lục"), await people("Đồng Đội")
    h, x = host.customer_id, mate.customer_id
    first = (await room_for(staff, admin, host.code))["room"]
    second = (await room_for(staff, admin, host.code))["room"]
    await add_match(first.id, 1, [h, x], [-1, -2], win="a")  # h, x thắng
    await add_match(first.id, 2, [-1, -2], [h, -3], win="a")  # h thua
    await add_match(first.id, 3, [h], [-1], status="abandoned")  # không tính
    await add_match(second.id, 1, [h], [-4], win="b")  # phòng khác: h thua
    async with SessionLocal() as s:
        got = await rooms.career_stats(s, {h, x, -9})
        assert await rooms.career_stats(s, set()) == {}
    assert (got[h].matches, got[h].wins) == (3, 1)
    assert (got[x].matches, got[x].wins) == (1, 1)
    assert -9 not in got  # chưa có trận nào
    # Khớp tổng Lịch sử chơi của tháng có các trận đó
    d = (await history(host.client)).json()
    assert (d["summary"]["matches"], d["summary"]["wins"]) == (got[h].matches, got[h].wins)
