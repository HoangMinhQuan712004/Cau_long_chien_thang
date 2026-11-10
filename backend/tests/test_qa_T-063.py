# ruff: noqa: E501
"""QA T-063 (API, AC1–AC6): ngày Lễ / Tết cho năm sau và sửa được (PATCH /booking/special-days/{id}).

Góc nhìn độc lập với ``test_special_day_update.py`` của BACKEND: năm sau thật (năm hiện tại + 1), biên năm 2000 / 2100,
ngày chạm nhau (liền kề không chồng), hai lần sửa đồng thời, tên biên 100 / 101 và chỉ khoảng trắng, ngày một ngày
(``date_to`` rỗng), mục ngày đã qua, Idempotency-Key thiếu / gửi lại, Origin lạ, quyền, danh sách theo năm không lẫn,
audit + catalog, giá booking đã đặt giữ nguyên và báo giá mới theo khoảng mới / khoảng cũ trở lại bình thường.
Mỗi test dọn dữ liệu của mình; dùng các năm 2087–2096 để không đụng ngày Lễ thật.
"""

import asyncio

import pytest
from sqlalchemy import delete, func, select

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.core.permissions import Perm
from app.modules.auth.models import RolePermission
from app.modules.booking_engine.models import Booking
from tests.conftest import API, idem
from tests.helpers_booking import BK, book, new_court, random_phone, safe_hour, temp, today


async def add(admin, date_from: str, name: str, date_to: str | None = None):
    return await admin.post(
        f"{BK}/special-days",
        json={"date_from": date_from, "date_to": date_to, "name": name},
        headers=idem(),
    )


async def make(admin, date_from: str, name: str, date_to: str | None = None) -> dict:
    r = await add(admin, date_from, name, date_to)
    assert r.status_code == 201, r.text
    return r.json()


async def patch(client, special_id: int, body: dict, headers: dict | None = None):
    return await client.patch(
        f"{BK}/special-days/{special_id}",
        json=body,
        headers=headers if headers is not None else idem(),
    )


async def drop(admin, *rows: dict) -> None:
    for row in rows:
        await admin.delete(f"{BK}/special-days/{row['id']}", headers=idem())


async def listed(admin, year: int) -> list[tuple[str, str, str]]:
    r = await admin.get(f"{BK}/special-days", params={"year": year})
    assert r.status_code == 200, r.text
    return [(d["date_from"], d["date_to"], d["name"]) for d in r.json()]


async def audit_count(row_id: int) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "config.special_day.update",
                AuditLog.entity_code == str(row_id),
            )
        )


# ---------------------------------------------------------------- AC1: năm sau


async def test_ac1_next_calendar_year_can_be_created_and_other_years_are_untouched(admin):
    nxt = today().year + 1
    # Ngày giữa năm sau, hiếm khi trùng ngày thật; nếu trùng (còn dữ liệu cũ) thì bỏ qua ca này
    r = await add(admin, f"{nxt}-07-14", "QA Tết năm sau")
    if r.status_code == 409:
        pytest.skip("năm sau đã có mục trùng ngày thử")
    assert r.status_code == 201, r.text
    row = r.json()
    try:
        here = await listed(admin, nxt)
        assert (f"{nxt}-07-14", f"{nxt}-07-14", "QA Tết năm sau") in here
        assert all(name != "QA Tết năm sau" for _, _, name in await listed(admin, today().year))
        assert all(name != "QA Tết năm sau" for _, _, name in await listed(admin, nxt + 1))
    finally:
        await drop(admin, row)
    assert all(name != "QA Tết năm sau" for _, _, name in await listed(admin, nxt))


async def test_ac1_year_boundaries_2000_and_2100_and_out_of_range(admin):
    for year in (2000, 2100):
        row = await make(admin, f"{year}-01-02", f"QA biên {year}")
        try:
            assert (f"{year}-01-02", f"{year}-01-02", f"QA biên {year}") in await listed(
                admin, year
            )
        finally:
            await drop(admin, row)
    for bad in (1999, 2101):
        r = await admin.get(f"{BK}/special-days", params={"year": bad})
        assert r.status_code == 422, (bad, r.status_code)


# ---------------------------------------------------------------- AC2/AC3: sửa, chồng, biên


async def test_ac2_ac3_touching_ranges_do_not_overlap_but_one_day_overlap_does(admin):
    a = await make(admin, "2090-05-10", "QA A", "2090-05-12")
    b = await make(admin, "2090-05-20", "QA B")
    try:
        # Liền kề (A kết thúc 12, B bắt đầu 13) -> không chồng
        r = await patch(admin, b["id"], {"date_from": "2090-05-13", "name": "QA B"})
        assert r.status_code == 200, r.text
        # Kéo dài A sang ngày 13 -> chồng đúng một ngày với B
        r = await patch(
            admin, a["id"], {"date_from": "2090-05-10", "date_to": "2090-05-13", "name": "QA A"}
        )
        assert r.status_code == 409 and r.json()["detail"]["code"] == "E-CFG-8", r.text
        assert "13/05" in r.json()["detail"]["message"] and "QA B" in r.json()["detail"]["message"]
        # Dữ liệu giữ nguyên sau lỗi
        assert await listed(admin, 2090) == [
            ("2090-05-10", "2090-05-12", "QA A"),
            ("2090-05-13", "2090-05-13", "QA B"),
        ]
        # B nuốt cả A (bao trùm) -> chồng
        r = await patch(
            admin, b["id"], {"date_from": "2090-05-09", "date_to": "2090-05-14", "name": "QA B"}
        )
        assert r.status_code == 409, r.text
        # Đổi tên + ngày cùng lúc, tự chồng với khoảng cũ của chính mình -> được
        r = await patch(
            admin, a["id"], {"date_from": "2090-05-11", "date_to": "2090-05-12", "name": "QA A mới"}
        )
        assert r.status_code == 200 and r.json()["name"] == "QA A mới", r.text
    finally:
        await drop(admin, a, b)


async def test_ac3_two_concurrent_edits_into_the_same_days_only_one_wins(admin):
    a = await make(admin, "2091-03-01", "QA song song A", "2091-03-02")
    b = await make(admin, "2091-03-10", "QA song song B", "2091-03-11")
    try:
        body = {"date_from": "2091-03-05", "date_to": "2091-03-06"}
        ra, rb = await asyncio.gather(
            patch(admin, a["id"], {**body, "name": "QA song song A"}),
            patch(admin, b["id"], {**body, "name": "QA song song B"}),
        )
        assert sorted([ra.status_code, rb.status_code]) == [200, 409], (ra.text, rb.text)
        loser = ra if ra.status_code == 409 else rb
        assert loser.json()["detail"]["code"] == "E-CFG-8"
        # Không còn hai mục cùng chiếm 5–6/3
        in_range = [
            x for x in await listed(admin, 2091) if x[0] <= "2091-03-06" and x[1] >= "2091-03-05"
        ]
        assert len(in_range) == 1, in_range
    finally:
        await drop(admin, a, b)


async def test_edit_validation_edges_names_dates_and_single_day(admin):
    row = await make(admin, "2092-02-02", "QA biên tên")
    try:
        ok_name = "Đ" * 100
        r = await patch(admin, row["id"], {"date_from": "2092-02-02", "name": ok_name})
        assert r.status_code == 200 and r.json()["name"] == ok_name
        for bad in ("Đ" * 101, "", "   "):
            r = await patch(admin, row["id"], {"date_from": "2092-02-02", "name": bad})
            assert r.status_code == 422, (len(bad), r.status_code, r.text)
        # Ngày ngược, vắt qua năm (cả hai chiều), ngày sai định dạng / không tồn tại
        for body in (
            {"date_from": "2092-02-05", "date_to": "2092-02-04", "name": "x"},
            {"date_from": "2092-12-31", "date_to": "2093-01-01", "name": "x"},
            {"date_from": "2091-12-31", "date_to": "2092-01-01", "name": "x"},
            {"date_from": "2092-02-30", "name": "x"},
            {"date_from": "02/02/2092", "name": "x"},
            {"name": "x"},
        ):
            r = await patch(admin, row["id"], body)
            assert r.status_code == 422, (body, r.status_code, r.text)
        # Dữ liệu vẫn nguyên sau mọi lần bị từ chối
        assert await listed(admin, 2092) == [("2092-02-02", "2092-02-02", ok_name)]
        # Chỉ có date_from -> một ngày; ngày cuối năm hợp lệ
        r = await patch(admin, row["id"], {"date_from": "2092-12-31", "name": "QA cuối năm"})
        assert r.status_code == 200 and r.json()["date_to"] == "2092-12-31", r.text
        # Đổi sang năm khác: danh sách năm cũ hết, năm mới có
        r = await patch(
            admin,
            row["id"],
            {"date_from": "2094-01-01", "date_to": "2094-01-03", "name": "QA sang năm"},
        )
        assert r.status_code == 200, r.text
        assert await listed(admin, 2092) == [] and await listed(admin, 2094) == [
            ("2094-01-01", "2094-01-03", "QA sang năm")
        ]
        # Id không tồn tại / không phải số
        assert (
            await patch(admin, 987_654_321, {"date_from": "2094-02-02", "name": "x"})
        ).status_code == 404
        r = await admin.patch(
            f"{BK}/special-days/abc", json={"date_from": "2094-02-02", "name": "x"}, headers=idem()
        )
        assert r.status_code == 422
    finally:
        await drop(admin, row)


async def test_ac2_can_edit_an_entry_in_the_past(admin):
    past = await make(admin, "2001-05-05", "QA quá khứ")
    try:
        r = await patch(
            admin,
            past["id"],
            {"date_from": "2001-05-05", "date_to": "2001-05-06", "name": "QA quá khứ sửa"},
        )
        assert r.status_code == 200 and r.json()["date_to"] == "2001-05-06", r.text
    finally:
        await drop(admin, past)


# ---------------------------------------------------------------- audit + catalog


async def test_ac2_audit_row_is_listed_in_history_and_catalog_has_labels(admin):
    row = await make(admin, "2093-04-04", "QA nhật ký")
    try:
        assert await audit_count(row["id"]) == 0, "tạo mới không phải dòng 'sửa'"
        assert (
            await patch(admin, row["id"], {"date_from": "2093-04-05", "name": "QA nhật ký 2"})
        ).status_code == 200
        assert await audit_count(row["id"]) == 1
        # Gửi y nguyên thì không thêm dòng
        assert (
            await patch(admin, row["id"], {"date_from": "2093-04-05", "name": "QA nhật ký 2"})
        ).status_code == 200
        assert await audit_count(row["id"]) == 1
        log = (
            await admin.get(
                f"{API}/admin/audit-log",
                params={"action": "config.special_day.update", "size": 50},
            )
        ).json()
        mine = [i for i in log["items"] if str(row["id"]) in str(i["target"])]
        assert len(mine) == 1, log["items"][:2]
        fields = {c["field"] for c in mine[0]["changes"]}
        assert {"Từ ngày", "Tên"} <= fields, mine[0]["changes"]
        cat = str((await admin.get(f"{API}/admin/audit-log/catalog")).json())
        assert cat.count("Lễ/Tết") >= 3, "có nhãn Thêm / Sửa / Xóa ngày Lễ/Tết"
    finally:
        await drop(admin, row)


# ---------------------------------------------------------------- AC5: giá


async def test_ac5_price_of_existing_booking_never_changes_and_quotes_follow_the_new_range(admin):
    court = await new_court(admin)
    day = today()
    hour = await safe_hour()
    quote = {
        "resource_code": court["code"],
        "date": day.isoformat(),
        "start_hour": hour,
        "end_hour": hour + 1,
    }

    async def q():
        r = await admin.post(f"{BK}/quote", json=quote)
        assert r.status_code == 200, r.text
        return r.json()

    base = await q()
    if base["day_type"] == "holiday":
        pytest.skip("hôm nay đã là ngày Lễ có sẵn")
    r = await book(admin, court["code"], hour, customer=temp("QA giá cũ", random_phone()), day=day)
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    row = await make(admin, "2088-06-15", "QA lễ giá")

    async def amount() -> int:
        async with SessionLocal() as s:
            return await s.scalar(select(Booking.amount).where(Booking.code == code))

    try:
        assert await amount() == base["total_amount"]
        # Dời lên hôm nay: booking giữ giá, báo giá mới là Lễ
        assert (
            await patch(admin, row["id"], {"date_from": day.isoformat(), "name": "QA lễ giá"})
        ).status_code == 200
        held = await q()
        assert held["day_type"] == "holiday"
        assert held["total_amount"] != base["total_amount"], "giá báo mới là giá Lễ"
        assert await amount() == base["total_amount"], "booking đã đặt giữ giá"
        # Dời đi chỗ khác: báo giá hôm nay trở lại như cũ, booking vẫn giữ giá
        assert (
            await patch(admin, row["id"], {"date_from": "2088-06-16", "name": "QA lễ giá"})
        ).status_code == 200
        back = await q()
        assert back["day_type"] == base["day_type"] and back["total_amount"] == base["total_amount"]
        assert await amount() == base["total_amount"]
    finally:
        await drop(admin, row)


# ---------------------------------------------------------------- AC6: quyền, Idempotency-Key, Origin


async def test_ac6_permissions_idempotency_and_origin(admin, staff, customer, anon):
    row = await make(admin, "2095-08-08", "QA quyền")
    body = {"date_from": "2095-08-09", "name": "QA quyền 2"}
    perm = Perm.BOOKING_CONFIG_MANAGE.value
    try:
        assert (await patch(anon, row["id"], body)).status_code == 401
        assert (await patch(customer, row["id"], body)).status_code == 403
        # Thiếu Idempotency-Key -> bị từ chối, không đổi dữ liệu
        miss = await admin.patch(f"{BK}/special-days/{row['id']}", json=body)
        assert miss.status_code in (400, 422), miss.text
        # Origin lạ -> 403
        evil = await admin.patch(
            f"{BK}/special-days/{row['id']}",
            json=body,
            headers={**idem(), "Origin": "https://evil.example"},
        )
        assert evil.status_code == 403, evil.text
        assert await listed(admin, 2095) == [("2095-08-08", "2095-08-08", "QA quyền")]
        # Gửi lại cùng khóa 3 lần song song -> 1 lần áp, cùng kết quả, 1 dòng nhật ký
        key = idem()
        rs = await asyncio.gather(*[patch(admin, row["id"], body, headers=key) for _ in range(3)])
        # Lượt đang xử lý có thể nhận E-SEC-3 ("đang được xử lý"); phải có ít nhất một lượt thắng và không lượt nào áp thêm
        ok = [r for r in rs if r.status_code == 200]
        busy = [r for r in rs if r.status_code != 200]
        assert ok and all(r.json()["detail"]["code"] == "E-SEC-3" for r in busy), [
            r.text for r in rs
        ]
        assert all(r.json() == ok[0].json() for r in ok)
        # Sau khi xong, gửi lại cùng khóa -> trả đúng kết quả cũ
        again = await patch(admin, row["id"], body, headers=key)
        assert again.status_code == 200 and again.json() == ok[0].json()
        assert await audit_count(row["id"]) == 1
        # Cùng khóa nhưng nội dung khác -> 409/422 (không áp lần hai)
        other = await patch(
            admin, row["id"], {"date_from": "2095-08-10", "name": "khác"}, headers=key
        )
        assert other.status_code in (409, 422), other.text
        assert await listed(admin, 2095) == [("2095-08-09", "2095-08-09", "QA quyền 2")]
        # Nhân viên mất quyền -> 403; có quyền -> sửa được
        async with SessionLocal() as s:
            await s.execute(
                delete(RolePermission).where(
                    RolePermission.role == "staff", RolePermission.perm == perm
                )
            )
            await s.commit()
        try:
            denied = await patch(staff, row["id"], {"date_from": "2095-08-11", "name": "NV"})
            assert denied.status_code == 403, denied.text
        finally:
            async with SessionLocal() as s:
                s.add(RolePermission(role="staff", perm=perm))
                await s.commit()
        allowed = await patch(staff, row["id"], {"date_from": "2095-08-11", "name": "NV có quyền"})
        assert allowed.status_code == 200, allowed.text
    finally:
        await drop(admin, row)
