# ruff: noqa: E501
"""QA T-053 (API, AC1–AC8): Bảng xếp hạng tốc độ xếp theo từng cú đập (đổi T-030).

Qua HTTP thật: một người chiếm nhiều bậc, thứ tự (km/h ↓, đạt sớm, id), mỗi bậc đúng video / ngày / sân của cú đó,
"Hạng của tôi" (cú tốt nhất, cách top 10, tên khớp bục), Tổng quan top 3, ẩn danh, điều kiện, ranh giới kỳ giờ VN,
ít hơn 3 cú, khối lượng lớn (SQL, không nạp hết lên bộ nhớ), và so với một oracle Python.
"""

import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, insert, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.members.models import Customer
from app.modules.records.models import SpeedRecord
from tests import test_play_rooms as base
from tests.conftest import _rate_limit_backend
from tests.helpers_booking import new_court
from tests.qa_queries import count_statements
from tests.test_play_rooms import MA

people = base.people
RANKING = f"{MA}/speed-ranking"
TAG = f"qa053:{uuid.uuid4().hex[:8]}:"
YT = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
YT2 = "https://youtu.be/9bZkp7q19f0"
MP4 = "https://cdn.example.com/clips/a.mp4"
_made: list[int] = []


async def person(people, name: str, **profile):
    if len(_made) % 8 == 7:
        _rate_limit_backend.clear()
    hv = await people(name)
    _made.append(hv.customer_id)
    async with SessionLocal() as s:
        await s.execute(
            update(Customer)
            .where(Customer.id == hv.customer_id)
            .values(show_on_records=profile.pop("show_on_records", True), **profile)
        )
        await s.commit()
    return hv


@pytest.fixture(autouse=True)
async def cleanup():
    """Bảng xếp hạng tính trên cả bảng: bắt đầu và kết thúc với bảng trống (DB test riêng)."""
    async with SessionLocal() as s:
        await s.execute(delete(SpeedRecord))
        await s.commit()
    yield
    async with SessionLocal() as s:
        await s.execute(delete(SpeedRecord))
        await s.commit()
    _made.clear()


def vn(y: int, m: int, d: int, h: int = 10, mi: int = 0, s: int = 0) -> datetime:
    return datetime(y, m, d, h, mi, s, tzinfo=settings.tz)


async def rec(cid, kmh, at, url=None, court=None, status="approved") -> int:
    async with SessionLocal() as s:
        r = SpeedRecord(
            customer_id=cid,
            speed_kmh=kmh,
            measured_at=at,
            court_code=court,
            status=status,
            reject_reason="x" if status == "rejected" else None,
            source_ref=f"{TAG}{uuid.uuid4()}",
        )
        r.set_video(url, at)
        s.add(r)
        await s.commit()
        return r.id


async def rank(client, period="month", day="2033-03-15") -> dict:
    r = await client.get(RANKING, params={"period": period, "date": day})
    assert r.status_code == 200, r.text
    return r.json()


# ---------------------------------------------------------------- AC1 / AC2 / AC5: nhiều bậc, thứ tự


async def test_ac1_one_member_with_three_shots_fills_the_podium_alone(admin, people):
    solo = await person(people, "QA Một Mình", nickname="Một Mình")
    court = await new_court(admin)
    await rec(solo.customer_id, 300, vn(2033, 3, 3), YT, court["code"])
    await rec(solo.customer_id, 290, vn(2033, 3, 4), None)
    await rec(solo.customer_id, 280, vn(2033, 3, 5), MP4)
    r = await rank(solo.client)
    assert [t["rank"] for t in r["top"]] == [1, 2, 3]
    assert [t["speed_kmh"] for t in r["top"]] == [300, 290, 280]
    assert {t["display_name"] for t in r["top"]} == {"Một Mình"} and all(
        t["is_me"] for t in r["top"]
    )
    assert (r["total_members"], r["total_records"]) == (1, 3)
    assert r["me"]["rank"] == 1 and r["me"]["speed_kmh"] == 300 and r["me"]["gap_to_top10"] is None
    # Mỗi bậc đúng cú của nó: ngày đạt, sân, video
    assert [
        datetime.fromisoformat(t["measured_at"]).astimezone(settings.tz).day for t in r["top"]
    ] == [3, 4, 5]
    assert [t["resource_name"] is not None for t in r["top"]] == [True, False, False], (
        "sân null thì để null"
    )
    assert [(t["video"] or {}).get("kind") for t in r["top"]] == ["youtube", None, "file"]
    assert r["top"][0]["resource_name"] == court["name"]


async def test_ac2_ac5_order_is_speed_then_earlier_then_id_even_for_the_same_person(people):
    a = await person(people, "QA Cùng Người A")
    b = await person(people, "QA Cùng Người B")
    ids = {}
    ids["a_late"] = await rec(a.customer_id, 280, vn(2033, 3, 9))
    ids["a_early"] = await rec(
        a.customer_id, 280, vn(2033, 3, 2)
    )  # cùng người, bằng km/h: đạt trước lên trên
    ids["b_mid"] = await rec(b.customer_id, 280, vn(2033, 3, 5))
    same_t = vn(2033, 3, 12)
    ids["b_x"] = await rec(b.customer_id, 270, same_t)  # cùng lúc đo: id nhỏ trước
    ids["a_y"] = await rec(a.customer_id, 270, same_t)
    ids["top"] = await rec(b.customer_id, 400, vn(2033, 3, 30))
    r = await rank(a.client)
    order = [t["speed_kmh"] for t in r["top"]]
    assert order == [400, 280, 280, 280, 270, 270]
    assert [t["rank"] for t in r["top"]] == [1, 2, 3, 4, 5, 6], "không đồng hạng"
    when = [
        datetime.fromisoformat(t["measured_at"]).astimezone(settings.tz).day for t in r["top"][1:4]
    ]
    assert when == [2, 5, 9], "bằng km/h: cú đạt trước xếp trên"
    assert [t["display_name"] for t in r["top"][1:4]] == [
        "QA Cùng Người A",
        "QA Cùng Người B",
        "QA Cùng Người A",
    ]
    tail = [t["is_me"] for t in r["top"][4:]]
    assert sorted(tail) == [False, True]
    assert ids["b_x"] < ids["a_y"] and r["top"][4]["is_me"] is False, "cùng lúc: id nhỏ xếp trên"


async def test_ac2_ranks_four_to_ten_are_per_shot_and_top_is_capped_at_ten(people):
    hv = [await person(people, f"QA Mười {i}") for i in range(4)]
    n = 0
    for i, p in enumerate(hv):
        for k in range(4):  # 16 cú
            await rec(p.customer_id, 300 - n, vn(2033, 3, 1 + k, 10 + i))
            n += 1
    r = await rank(hv[3].client)
    assert len(r["top"]) == 10 and [t["rank"] for t in r["top"]] == list(range(1, 11))
    assert r["total_records"] == 16 and r["total_members"] == 4
    assert [t["speed_kmh"] for t in r["top"]] == list(range(300, 290, -1))
    # hv[3] có cú xếp 13–16 (288 … 285): hạng của tôi = cú tốt nhất = 13, cách top 10 = 291 − 288
    assert r["me"]["rank"] == 13 and r["me"]["speed_kmh"] == 288 and r["me"]["gap_to_top10"] == 3
    assert not any(t["is_me"] for t in r["top"])


# ---------------------------------------------------------------- AC3: video đúng cú


async def test_ac3_each_row_has_the_video_of_its_own_shot_only(people):
    a = await person(people, "QA Video Từng Cú")
    await rec(a.customer_id, 310, vn(2033, 3, 2), None)  # cú tốt nhất không video
    await rec(a.customer_id, 300, vn(2033, 3, 3), YT)
    await rec(a.customer_id, 290, vn(2033, 3, 4), YT2)
    r = await rank(a.client)
    assert [(t["speed_kmh"], (t["video"] or {}).get("url")) for t in r["top"]] == [
        (310, None),
        (300, YT),
        (290, YT2),
    ]
    assert r["me"]["speed_kmh"] == 310 and r["me"]["video"] is None, (
        "khối của tôi: video của cú tốt nhất"
    )
    assert "customer_id" not in str(r) and "public_id" not in str(r)


# ---------------------------------------------------------------- AC4: Hạng của tôi


async def test_ac4_my_card_name_avatar_match_the_podium_and_all_my_rows_are_marked(people):
    me = await person(people, "Họ Tên Dài Của Tôi", nickname="Biệt Danh Tôi")
    plain = await person(people, "QA Không Biệt Danh", nickname=None)
    await rec(me.customer_id, 330, vn(2033, 3, 2))
    await rec(plain.customer_id, 320, vn(2033, 3, 3))
    await rec(me.customer_id, 310, vn(2033, 3, 4))
    r = await rank(me.client)
    mine = [t for t in r["top"] if t["is_me"]]
    assert len(mine) == 2 and {t["display_name"] for t in mine} == {"Biệt Danh Tôi"}
    assert r["me"]["display_name"] == "Biệt Danh Tôi" == mine[0]["display_name"], (
        "thẻ và bục cùng tên"
    )
    assert r["me"]["avatar_url"] == mine[0]["avatar_url"]
    other = await rank(plain.client)
    assert other["me"]["display_name"] == "QA Không Biệt Danh" and other["me"]["rank"] == 2
    assert [t["display_name"] for t in other["top"]].count("QA Không Biệt Danh") == 1
    assert "Họ Tên Dài Của Tôi" not in str(r), "có biệt danh thì không dùng họ tên"


async def test_ac4_gap_to_top10_uses_my_best_shot_and_hides_inside_top10(people):
    crowd = [await person(people, f"QA Đông {i}") for i in range(5)]
    me = await person(people, "QA Cách Top Mười")
    for i, p in enumerate(crowd):
        for k in range(2):  # 10 cú, 400 … 391
            await rec(p.customer_id, 400 - (i * 2 + k), vn(2033, 3, 1 + k))
    await rec(me.customer_id, 380, vn(2033, 3, 6))
    await rec(me.customer_id, 370, vn(2033, 3, 7))
    r = await rank(me.client)
    assert r["me"]["rank"] == 11 and r["me"]["gap_to_top10"] == 391 - 380
    assert r["total_records"] == 12
    await rec(me.customer_id, 395, vn(2033, 3, 8))  # lọt top 10
    r = await rank(me.client)
    assert (
        r["me"]["rank"] == 7 and r["me"]["gap_to_top10"] is None
    )  # 395 đạt sau cú 395 của đám đông
    assert [t["is_me"] for t in r["top"]].count(True) == 1


# ---------------------------------------------------------------- AC6: Tổng quan


async def test_ac6_overview_top3_and_my_rank_follow_the_per_shot_rule(people):
    a = await person(people, "QA Tổng Quan Một", nickname="Tổng Quan Một")
    b = await person(people, "QA Tổng Quan Hai")
    now = datetime.now(UTC).astimezone(settings.tz)
    base_t = now - timedelta(minutes=30)
    await rec(a.customer_id, 340, base_t, YT)
    await rec(a.customer_id, 330, base_t + timedelta(minutes=1))
    await rec(a.customer_id, 320, base_t + timedelta(minutes=2))
    await rec(b.customer_id, 300, base_t + timedelta(minutes=3))
    ov = (await a.client.get(f"{MA}/overview")).json()["ranking"]
    assert [t["speed_kmh"] for t in ov["top3"]] == [340, 330, 320]
    assert [t["display_name"] for t in ov["top3"]] == ["Tổng Quan Một"] * 3, (
        "một người chiếm cả top 3"
    )
    assert ov["total_records"] == 4 and ov["total_members"] == 2
    assert ov["me"]["rank"] == 1 and ov["me"]["gap_to_top10"] is None
    assert ov["top3"][0]["video"]["url"] == YT
    ov_b = (await b.client.get(f"{MA}/overview")).json()["ranking"]
    assert ov_b["me"]["rank"] == 4 and ov_b["total_records"] == 4
    # Tổng quan khớp màn Bảng xếp hạng cùng tháng
    full = await rank(a.client, "month", now.date().isoformat())
    assert [t["speed_kmh"] for t in full["top"][:3]] == [t["speed_kmh"] for t in ov["top3"]]
    assert full["me"]["rank"] == ov["me"]["rank"] and full["total_records"] == ov["total_records"]


# ---------------------------------------------------------------- AC7: riêng tư, điều kiện, kỳ


async def test_ac7_anonymous_member_holding_several_places_stays_anonymous(people):
    hidden = await person(
        people, "QA Tên Thật Ẩn Nhiều Bậc", nickname="Biệt Danh Ẩn", show_on_records=False
    )
    shown = await person(people, "QA Người Thấy")
    for k, kmh in enumerate((350, 340, 330)):
        await rec(hidden.customer_id, kmh, vn(2033, 3, 2 + k), YT)
    await rec(shown.customer_id, 300, vn(2033, 3, 8))
    r = await shown.client.get(RANKING, params={"period": "month", "date": "2033-03-15"})
    d = r.json()
    assert [t["display_name"] for t in d["top"][:3]] == ["Hội viên ẩn danh"] * 3
    assert all(t["avatar_url"] is None for t in d["top"][:3])
    for leak in (
        "QA Tên Thật Ẩn Nhiều Bậc",
        "Biệt Danh Ẩn",
        hidden.code,
        hidden.phone,
        "customer_id",
        "public_id",
        "email",
    ):
        assert leak not in r.text, leak
    assert all(t["video"] for t in d["top"][:3]), "ẩn danh vẫn phát video"
    own = await rank(hidden.client)
    assert all(
        t["display_name"] == "QA Tên Thật Ẩn Nhiều Bậc" or t["display_name"] == "Biệt Danh Ẩn"
        for t in own["top"][:3]
    )
    assert own["me"]["rank"] == 1


async def test_ac7_only_approved_active_linked_and_period_bounds_in_vn_time(people):
    a = await person(people, "QA Điều Kiện Một")
    stopped = await person(people, "QA Đã Ngừng")
    await rec(a.customer_id, 200, vn(2033, 3, 1, 0, 0, 0))  # 00:00:00 đầu tháng: trong tháng 3
    await rec(a.customer_id, 210, vn(2033, 2, 28, 23, 59, 59))  # trước nửa đêm: tháng 2
    await rec(a.customer_id, 220, vn(2033, 3, 31, 23, 59, 59))  # cuối tháng 3
    await rec(a.customer_id, 230, vn(2033, 4, 1, 0, 0, 0))  # tháng 4
    await rec(a.customer_id, 499, vn(2033, 3, 10), status="pending")
    await rec(a.customer_id, 498, vn(2033, 3, 11), status="rejected")
    await rec(stopped.customer_id, 450, vn(2033, 3, 12))
    async with SessionLocal() as s:
        await s.execute(
            update(Customer).where(Customer.id == stopped.customer_id).values(is_active=False)
        )
        await s.commit()
    march = await rank(a.client, "month", "2033-03-15")
    assert [t["speed_kmh"] for t in march["top"]] == [220, 200]
    assert march["total_records"] == 2 and march["total_members"] == 1
    feb = await rank(a.client, "month", "2033-02-15")
    assert [t["speed_kmh"] for t in feb["top"]] == [210]
    apr = await rank(a.client, "month", "2033-04-15")
    assert [t["speed_kmh"] for t in apr["top"]] == [230]
    year = await rank(a.client, "year", "2033-06-01")
    assert [t["speed_kmh"] for t in year["top"]] == [230, 220, 210, 200] and year[
        "total_records"
    ] == 4


# ---------------------------------------------------------------- AC8: ít cú, bảng rỗng


async def test_ac8_fewer_than_three_shots_shows_only_real_rows_and_empty_period_is_empty(people):
    a = await person(people, "QA Ít Cú")
    assert (await rank(a.client))["top"] == [] and (await rank(a.client))["me"] is None
    assert (await rank(a.client))["total_records"] == 0
    await rec(a.customer_id, 250, vn(2033, 3, 3))
    r = await rank(a.client)
    assert len(r["top"]) == 1 and r["total_records"] == 1 and r["me"]["rank"] == 1
    await rec(a.customer_id, 240, vn(2033, 3, 4))
    assert len((await rank(a.client))["top"]) == 2


# ---------------------------------------------------------------- oracle + khối lượng


async def test_ranking_matches_a_python_oracle_for_random_data(people):
    rng = random.Random(53)
    hv = [await person(people, f"QA Oracle {i}") for i in range(5)]
    rows = []
    async with SessionLocal() as s:
        for _ in range(60):
            p = rng.choice(hv)
            at = vn(2033, 3, rng.randint(1, 28), rng.randint(0, 23), rng.choice((0, 15, 30, 45)))
            kmh = rng.randint(180, 260)
            r = SpeedRecord(
                customer_id=p.customer_id,
                speed_kmh=kmh,
                measured_at=at,
                source_ref=f"{TAG}{uuid.uuid4()}",
            )
            s.add(r)
            await s.flush()
            rows.append((kmh, at, r.id, p.customer_id))
        await s.commit()
    expected = sorted(rows, key=lambda x: (-x[0], x[1], x[2]))
    d = await rank(hv[0].client)
    assert d["total_records"] == len(rows)
    assert [t["speed_kmh"] for t in d["top"]] == [x[0] for x in expected[:10]]
    assert [datetime.fromisoformat(t["measured_at"]) for t in d["top"]] == [
        x[1] for x in expected[:10]
    ]
    for p in hv:
        mine = [i for i, x in enumerate(expected, 1) if x[3] == p.customer_id]
        got = (await rank(p.client))["me"]
        assert (got["rank"] if got else None) == (mine[0] if mine else None)
        if got and got["rank"] > 10:
            assert got["gap_to_top10"] == expected[9][0] - got["speed_kmh"]


async def test_large_data_is_summarised_in_sql_and_stays_fast(people):
    hv = [await person(people, f"QA Khối Lượng {i}") for i in range(3)]
    base_t = vn(2033, 3, 1)
    rows = [
        {
            "customer_id": hv[i % 3].customer_id,
            "speed_kmh": 50 + (i % 451),
            "measured_at": base_t + timedelta(minutes=i),
            "source_ref": f"{TAG}bulk{i}",
        }
        for i in range(3000)
    ]
    async with SessionLocal() as s:
        for k in range(0, len(rows), 500):
            await s.execute(insert(SpeedRecord), rows[k : k + 500])
        await s.commit()
    with count_statements() as n:
        d = await rank(hv[0].client)
    assert d["total_records"] == 3000 and len(d["top"]) == 10
    assert [t["speed_kmh"] for t in d["top"]] == [500] * 6 + [499] * 4
    print("T053 rank statements", n[0])
    assert n[0] <= 15, (
        f"bảng xếp hạng chạy {n[0]} câu SQL với 3000 bản ghi (không đo ms – T-067 AC3)"
    )
