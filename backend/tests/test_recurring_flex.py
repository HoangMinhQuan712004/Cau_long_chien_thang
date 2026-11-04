"""T-043: đặt sân định kỳ linh động – gợi ý cho buổi trùng, buổi tường minh, nhiều sân / đơn."""

from datetime import timedelta

from tests.conftest import idem
from tests.helpers_booking import BK, new_court, temp, today
from tests.test_recurring import FD, body, error, preview, quote

CREATE = f"{FD}/recurring"


def sess(day, court: dict, a: int, b: int) -> dict:
    return {"date": day.isoformat(), "resource_code": court["code"], "start_hour": a, "end_hour": b}


async def block_with_event(admin, court: dict, day, a: int, b: int) -> None:
    r = await admin.post(
        f"{BK}/sessions",
        json={
            "resource_codes": [court["code"]],
            "date": day.isoformat(),
            "start_hour": a,
            "end_hour": b,
            "name": "Sự kiện chặn T-043",
            "capacity": 8,
            "ticket_price": 50_000,
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text


async def test_suggestions_shift_and_other_court_with_prices(admin):
    court = await new_court(admin, open_time="06:00", close_time="22:00")
    day = today() + timedelta(days=40)
    await block_with_event(admin, court, day, 18, 20)

    d = await preview(admin, body(court, day, day, weekdays=(day.isoweekday(),)))
    [s] = d["sessions"]
    assert (s["ok"], s["reason"], s["resource_code"]) == (False, "event", court["code"])
    kinds = {g["kind"]: g for g in s["suggestions"]}
    assert set(kinds) == {"shift", "court"} and len(s["suggestions"]) <= 2
    shift = kinds["shift"]
    # 17–19 và 19–21 vẫn chạm sự kiện; gần nhất còn trống: 16–18 (bằng 20–22, lấy giờ sớm hơn)
    assert (shift["resource_code"], shift["start_hour"], shift["end_hour"]) == (
        court["code"],
        16,
        18,
    )
    assert shift["price"] == await quote(admin, court, day, (16, 18))
    other = kinds["court"]
    assert other["resource_code"] != court["code"]
    assert (other["start_hour"], other["end_hour"]) == (18, 20)
    assert other["price"] == await quote(admin, {"code": other["resource_code"]}, day, (18, 20))

    # Ngoài giờ mở cửa -> không gợi ý
    d = await preview(admin, body(court, day, day, weekdays=(day.isoweekday(),), hours=(21, 23)))
    assert d["sessions"][0]["reason"] == "closed" and d["sessions"][0]["suggestions"] == []


async def test_explicit_sessions_apply_suggestion_skip_and_mix_courts(admin):
    a, b = await new_court(admin), await new_court(admin)
    start = today() + timedelta(days=45)
    week = [start + timedelta(days=7 * i) for i in range(3)]
    await block_with_event(admin, a, week[1], 18, 20)

    # Lịch chung: buổi tuần 2 trùng; Admin dời buổi đó sang sân B, bỏ buổi tuần 3
    data = body(a, week[0], week[2], weekdays=(start.isoweekday(),), pct=10)
    d = await preview(admin, data)
    assert [x["ok"] for x in d["sessions"]] == [True, False, True]
    fixed = [sess(week[0], a, 18, 20), sess(week[1], b, 18, 20)]
    d = await preview(admin, {**data, "sessions": fixed})
    assert d["count"] == 2 and d["conflicts_count"] == 0
    assert [x["resource_code"] for x in d["sessions"]] == [a["code"], b["code"]]
    assert sum(x["price_after_discount"] for x in d["sessions"]) == d["total"]

    r = await admin.post(
        CREATE,
        json={**data, "sessions": fixed, "customer": temp("Khách Linh Động")},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    out = r.json()
    assert [x["schedule"]["resource_codes"] for x in out["bookings"]] == [[a["code"]], [b["code"]]]
    assert [x["schedule"]["play_date"] for x in out["bookings"]] == [
        week[0].isoformat(),
        week[1].isoformat(),
    ]
    assert out["total"] == d["total"] and out["order_code"].startswith(f"BK-{week[0]:%Y%m%d}-")

    # Tranh chấp: đặt lại buổi đã có -> 409 E-BOOK-5 kèm gợi ý mới
    r = await admin.post(
        CREATE,
        json={**data, "sessions": [sess(week[0], a, 18, 20)], "customer": temp("Khách Sau")},
        headers=idem(),
    )
    assert r.status_code == 409 and error(r) == "E-BOOK-5"
    [conflict] = r.json()["detail"]["conflicts"]
    assert conflict["reason"] == "booked" and conflict["resource_code"] == a["code"]
    assert conflict["suggestions"]


async def test_explicit_sessions_validation(admin):
    court = await new_court(admin)
    start = today() + timedelta(days=3)
    base = body(court, start, start + timedelta(days=6))
    bad = [
        [],  # không còn buổi nào
        [sess(today() - timedelta(days=1), court, 18, 20)],  # ngày đã qua
        [sess(start, court, 20, 18)],  # giờ ngược
        [sess(start, court, 18, 20), sess(start, court, 19, 21)],  # cùng sân chồng giờ
        [sess(start, court, 18, 20), sess(start + timedelta(days=92), court, 18, 20)],  # > 92 ngày
        [sess(start + timedelta(days=i), court, 6, 7) for i in range(61)],  # > 60 buổi
    ]
    for sessions in bad:
        r = await admin.post(f"{FD}/recurring/preview", json={**base, "sessions": sessions})
        assert r.status_code == 422, (sessions[:2], r.text)
    # Cùng ngày, hai sân khác nhau, cùng giờ -> hợp lệ (đơn nhiều sân)
    other = await new_court(admin)
    d = await preview(
        admin, {**base, "sessions": [sess(start, court, 18, 20), sess(start, other, 18, 20)]}
    )
    assert d["count"] == 2 and d["conflicts_count"] == 0
    r = await admin.post(
        f"{FD}/recurring/preview",
        json={**base, "sessions": [{**sess(start, court, 18, 20), "resource_code": "ZZ99"}]},
    )
    assert r.status_code == 404
