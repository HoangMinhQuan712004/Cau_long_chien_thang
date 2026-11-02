# ruff: noqa: E501, F811
"""QA T-030 giai đoạn A (API): Bảng xếp hạng tốc độ `GET /member-area/speed-ranking` (AC2, AC3, AC4, AC6) – viết từ spec, độc lập với test BE.

Số đo chỉ có ở DB (không có endpoint ghi ở giai đoạn A) nên chèn bằng SQL; hội viên đăng nhập = đăng ký OTP 2 bước. Kỳ dùng năm 2033 để không đụng dữ liệu khác.
"""

import base64
import json
import os
import subprocess
import sys
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.db import engine
from tests.conftest import API, BACKEND_DIR, _rate_limit_backend
from tests.qa_rooms import err, people  # noqa: F401  (fixture: hội viên có tài khoản liên kết)

MA = f"{API}/member-area"
RANKING = f"{MA}/speed-ranking"
TAG = f"qa30:{uuid.uuid4().hex[:8]}:"


async def q(sql: str, **params):
    async with engine.begin() as conn:
        return (await conn.execute(text(sql), params)).mappings().all()


@pytest.fixture(autouse=True)
async def cleanup():
    yield
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM speed_record WHERE source_ref LIKE :t"), {"t": f"{TAG}%"}
        )


def vn(y, m, d, h=10, mi=0) -> datetime:
    return datetime(y, m, d, h, mi, tzinfo=settings.tz)


async def rec(cid: int, kmh: int, at: datetime) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO speed_record (customer_id, speed_kmh, measured_at, source_ref) VALUES (:c, :k, :a, :s)"
            ),
            {"c": cid, "k": kmh, "a": at, "s": f"{TAG}{uuid.uuid4()}"},
        )


async def profile(cid: int, **values) -> None:
    sets = ", ".join(f"{k} = :{k}" for k in values)
    async with engine.begin() as conn:
        await conn.execute(
            text(f"UPDATE customer SET {sets} WHERE id = :cid"), {**values, "cid": cid}
        )


async def rank(c, period="month", day="2033-03-15"):
    r = await c.get(RANKING, params={"period": period, "date": day})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    return r.json()


async def members(people, n: int, prefix="Tay Vợt"):
    out = []
    for i in range(n):
        _rate_limit_backend.clear()  # nhiều lần đăng ký OTP cùng IP vượt giới hạn
        out.append(await people(f"{prefix} {i:02d} {uuid.uuid4().hex[:4]}"))
    for p in out:
        p.customer_id = (await q("SELECT id FROM customer WHERE phone = :p", p=p.phone))[0]["id"]
        await profile(p.customer_id, show_on_records=True)
    return out


# ============================================================ AC2: xếp hạng, đồng tốc, kỳ, khoảng cách top 10


async def test_ac2_order_best_per_member_ties_earlier_wins_and_continuous_ranks(people):
    hv = await members(people, 4)
    a, b, c, d = hv
    await rec(a.customer_id, 280, vn(2033, 3, 8))
    await rec(a.customer_id, 240, vn(2033, 3, 9))  # thấp hơn của chính mình: không tính
    await rec(b.customer_id, 280, vn(2033, 3, 5))  # bằng a nhưng đạt trước -> trên a
    await rec(c.customer_id, 300, vn(2033, 3, 20))
    await rec(d.customer_id, 210, vn(2033, 3, 1))
    r = await rank(a.client)
    assert [t["rank"] for t in r["top"]] == [1, 2, 3, 4], "hạng liên tục, không đồng hạng"
    mine = {t["display_name"]: t for t in r["top"]}
    assert [t["speed_kmh"] for t in r["top"]] == [300, 280, 280, 210]
    assert [t["display_name"] for t in r["top"]] == [c.name, b.name, a.name, d.name]
    assert r["me"]["rank"] == 3 and r["me"]["speed_kmh"] == 280 and r["me"]["gap_to_top10"] is None
    assert mine[a.name]["is_me"] is True and sum(t["is_me"] for t in r["top"]) == 1
    assert (r["period"], r["start"], r["end"], r["bar_floor_kmh"]) == (
        "month",
        "2033-03-01",
        "2033-03-31",
        200,
    )
    assert r["total_members"] == 4 and r["me"]["measured_at"]


async def test_ac2_top_is_capped_at_10_and_gap_to_top10_for_the_rest(people):
    hv = await members(people, 12)
    for i, p in enumerate(hv[:10]):
        await rec(p.customer_id, 400 - i * 10, vn(2033, 4, 3))  # 400 … 310
    await rec(hv[10].customer_id, 305, vn(2033, 4, 3))
    await rec(hv[11].customer_id, 250, vn(2033, 4, 3))
    r = await rank(hv[10].client, "month", "2033-04-10")
    assert len(r["top"]) == 10 and r["total_members"] == 12
    assert r["top"][-1]["speed_kmh"] == 310
    assert r["me"]["rank"] == 11 and r["me"]["gap_to_top10"] == 5, "hạng 10 − của mình = 310 − 305"
    r2 = await rank(hv[11].client, "month", "2033-04-10")
    assert r2["me"]["rank"] == 12 and r2["me"]["gap_to_top10"] == 60
    r3 = await rank(hv[3].client, "month", "2033-04-10")
    assert r3["me"]["rank"] == 4 and r3["me"]["gap_to_top10"] is None, (
        "trong top 10 thì không có khoảng cách"
    )


async def test_ac2_periods_week_month_year_boundaries_in_vn_time(people):
    hv = await members(people, 1)
    me = hv[0]
    # 2033-03-06 là Chủ nhật, 2033-03-07 là Thứ hai
    assert datetime(2033, 3, 6).weekday() == 6
    await rec(
        me.customer_id, 260, vn(2033, 3, 6, 23, 30)
    )  # CN 23:30 giờ VN: tuần T2 28/02 → CN 06/03
    await rec(me.customer_id, 270, vn(2033, 3, 7, 0, 30))  # T2 00:30 giờ VN: tuần kế
    w1 = await rank(me.client, "week", "2033-03-04")
    assert (w1["start"], w1["end"]) == ("2033-02-28", "2033-03-06") and w1["me"]["speed_kmh"] == 260
    w2 = await rank(me.client, "week", "2033-03-09")
    assert (w2["start"], w2["end"]) == ("2033-03-07", "2033-03-13") and w2["me"]["speed_kmh"] == 270
    # đầu tháng / cuối tháng theo giờ VN: 31/03 17:30 UTC = 01/04 00:30 VN → tháng 4
    await rec(me.customer_id, 310, datetime(2033, 3, 31, 17, 30, tzinfo=UTC))
    m3 = await rank(me.client, "month", "2033-03-20")
    m4 = await rank(me.client, "month", "2033-04-20")
    assert m3["me"]["speed_kmh"] == 270 and m4["me"]["speed_kmh"] == 310
    assert (m3["start"], m3["end"]) == ("2033-03-01", "2033-03-31") and (
        m4["start"],
        m4["end"],
    ) == ("2033-04-01", "2033-04-30")
    y = await rank(me.client, "year", "2033-12-31")
    assert (y["start"], y["end"]) == ("2033-01-01", "2033-12-31") and y["me"]["speed_kmh"] == 310
    empty = await rank(me.client, "month", "2033-09-01")
    assert empty["top"] == [] and empty["me"] is None and empty["total_members"] == 0


async def test_ac2_default_params_and_validation_errors(people, anon, customer):
    me = (await members(people, 1))[0]
    d = (await me.client.get(RANKING)).json()
    today = datetime.now(settings.tz).date()
    assert d["period"] == "month" and d["start"] == today.replace(day=1).isoformat()
    for params in (
        {"period": "day"},
        {"period": "Week"},
        {"date": "2033-02-30"},
        {"date": "abc"},
        {"date": "2033-3-1"},
        {"period": "month", "date": ""},
    ):
        assert (await me.client.get(RANKING, params=params)).status_code == 422, params
    assert (await anon.get(RANKING)).status_code == 401
    r = await customer.get(RANKING)
    assert r.status_code == 403 and err(r)["code"] == "E-HV-8"


# ============================================================ AC4: riêng tư và loại trừ


async def test_ac4_anonymous_members_keep_their_rank_but_leak_nothing(people):
    hv = await members(people, 3)
    shy, other, viewer = hv
    await profile(shy.customer_id, show_on_records=False)
    await rec(shy.customer_id, 330, vn(2033, 5, 5))
    await rec(other.customer_id, 300, vn(2033, 5, 6))
    await rec(viewer.customer_id, 250, vn(2033, 5, 7))
    r = await viewer.client.get(RANKING, params={"period": "month", "date": "2033-05-10"})
    body = r.text
    top = r.json()["top"]
    assert (
        top[0]["rank"] == 1
        and top[0]["display_name"] == "Hội viên ẩn danh"
        and top[0]["avatar_url"] is None
    ), "vẫn xếp hạng nhưng ẩn danh"
    assert top[0]["is_me"] is False
    assert shy.name not in body and shy.phone not in body and shy.code not in body, (
        "không lộ tên / SĐT / mã hội viên của người ẩn danh"
    )
    assert f"avatars/{shy.customer_id}" not in body, (
        "không lộ id của người ẩn danh qua đường dẫn ảnh"
    )
    assert f'"{shy.customer_id}"' not in body and f":{shy.customer_id}," not in body
    for p in hv:
        assert p.phone not in body and p.code not in body or p is viewer
    assert "customer_id" not in body and "public_id" not in body
    # chính mình luôn thấy tên mình, kể cả khi bật ẩn danh
    r2 = await shy.client.get(RANKING, params={"period": "month", "date": "2033-05-10"})
    mine = r2.json()["top"][0]
    assert mine["is_me"] is True and mine["display_name"] == shy.name
    # người khác trong bảng hiện tên bình thường
    assert next(t for t in top if t["rank"] == 2)["display_name"] == other.name


async def test_ac4_inactive_members_are_excluded_and_not_counted(people):
    hv = await members(people, 3)
    a, stopped, me = hv
    await rec(a.customer_id, 300, vn(2033, 6, 5))
    await rec(stopped.customer_id, 500, vn(2033, 6, 6))
    await rec(me.customer_id, 280, vn(2033, 6, 7))
    await profile(stopped.customer_id, is_active=False)
    r = await rank(me.client, "month", "2033-06-10")
    assert [t["display_name"] for t in r["top"]] == [a.name, me.name], (
        "hội viên Ngừng không vào bảng"
    )
    assert r["total_members"] == 2 and r["me"]["rank"] == 2
    await profile(stopped.customer_id, is_active=True)
    assert (await rank(me.client, "month", "2033-06-10"))["total_members"] == 3


async def test_ac4_members_without_a_linked_verified_account_are_excluded(people):
    hv = await members(people, 2)
    a, me = hv
    await rec(a.customer_id, 300, vn(2033, 7, 5))
    await rec(me.customer_id, 280, vn(2033, 7, 6))
    # hồ sơ do quầy tạo nhưng tài khoản bị gỡ SĐT → không còn liên kết
    async with engine.begin() as conn:
        await conn.execute(
            text("UPDATE users SET phone_verified_at = NULL WHERE phone = :p"), {"p": a.phone}
        )
    r = await rank(me.client, "month", "2033-07-10")
    assert [t["display_name"] for t in r["top"]] == [me.name], (
        "tài khoản chưa xác minh SĐT thì không còn liên kết → không vào bảng"
    )
    assert r["total_members"] == 1


# ============================================================ AC3: record_kmh ở /member-area/me


async def test_ac3_record_kmh_is_the_all_time_best_and_null_without_records(people):
    me = (await members(people, 1))[0]
    assert (await me.client.get(f"{MA}/me")).json()["record_kmh"] is None
    await rec(me.customer_id, 240, vn(2031, 1, 5))
    await rec(me.customer_id, 295, vn(2032, 8, 5))
    await rec(me.customer_id, 270, vn(2033, 2, 5))
    assert (await me.client.get(f"{MA}/me")).json()["record_kmh"] == 295, (
        "kỷ lục mọi thời gian, không theo kỳ"
    )


# ============================================================ ràng buộc DB, seed, migration


async def test_db_constraints_speed_range_and_unique_source_ref(people):
    me = (await members(people, 1))[0]
    for bad in (49, 501, 0, -5):
        with pytest.raises(IntegrityError, match="check|speed"):
            await rec(me.customer_id, bad, vn(2033, 8, 1))
    await rec(me.customer_id, 50, vn(2033, 8, 1))
    await rec(me.customer_id, 500, vn(2033, 8, 2))  # biên hợp lệ
    ref = f"{TAG}dup"
    async with engine.begin() as conn:
        await conn.execute(
            text(
                "INSERT INTO speed_record (customer_id, speed_kmh, measured_at, source_ref) VALUES (:c, 200, now(), :s)"
            ),
            {"c": me.customer_id, "s": ref},
        )
    with pytest.raises(IntegrityError, match="unique|duplicate"):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO speed_record (customer_id, speed_kmh, measured_at, source_ref) VALUES (:c, 210, now(), :s)"
                ),
                {"c": me.customer_id, "s": ref},
            )
    with pytest.raises(IntegrityError, match="null|not-null"):
        async with engine.begin() as conn:
            await conn.execute(
                text(
                    "INSERT INTO speed_record (customer_id, speed_kmh, measured_at, source_ref) VALUES (NULL, 200, now(), :s)"
                ),
                {"s": f"{TAG}nullcust"},
            )


async def test_ac6_seed_refuses_production_and_there_is_no_write_endpoint(people):
    before = (await q("SELECT count(*) AS n FROM speed_record"))[0]["n"]
    # cấu hình production hợp lệ (nếu không, Settings dừng với mã 1 trước khi seed kịp từ chối)
    env = {
        **os.environ,
        "ENV": "production",
        "PAYMENTS_SIMULATE": "false",
        "OTP_TEST_MODE": "false",
        "SECRET_KEY": "x" * 40,
        "PAYMENTS_ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
    }
    r = subprocess.run(
        [sys.executable, "-m", "app.modules.records.seed_demo"],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert r.returncode == 2, (r.returncode, r.stdout[-300:], r.stderr[-300:])
    assert (await q("SELECT count(*) AS n FROM speed_record"))[0]["n"] == before, (
        "production: không ghi gì"
    )
    me = (await members(people, 1))[0]
    for method in ("post", "put", "patch", "delete"):
        resp = await getattr(me.client, method)(
            RANKING, headers={"Idempotency-Key": str(uuid.uuid4())}
        )
        assert resp.status_code in (404, 405), (method, resp.status_code)
    spec = await me.client.get(f"{API}/openapi.json")
    if spec.status_code == 200:
        assert "speed-readings" not in json.dumps(spec.json()["paths"]), (
            "giai đoạn A chưa có endpoint ghi số đo từ máy"
        )


async def test_migration_head_is_single_and_speed_record_has_its_indexes():
    out = subprocess.run(
        [sys.executable, "-m", "alembic", "heads"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        timeout=120,
    )
    heads = [ln for ln in out.stdout.splitlines() if "(head)" in ln]
    assert len(heads) == 1, f"phải có đúng 1 head, đang có: {heads}"
    idx = await q("SELECT indexdef FROM pg_indexes WHERE tablename = 'speed_record'")
    defs = " ".join(r["indexdef"] for r in idx)
    assert "measured_at" in defs and "customer_id" in defs and "speed_kmh" in defs
    cols = await q(
        "SELECT column_name, is_nullable FROM information_schema.columns WHERE table_name = 'speed_record'"
    )
    nullable = {r["column_name"]: r["is_nullable"] for r in cols}
    assert nullable["customer_id"] == "NO" and nullable["source_ref"] == "NO", nullable
