# ruff: noqa: E501
"""QA T-022 (PR #22 – màn Lịch sử thao tác, chỉ Admin): quyền, lọc, sắp xếp, phân trang, nội dung dòng cho các thao tác mới
(T-019 mã đơn/mã khối, T-016 hội viên tự sửa + ảnh, T-020 sửa hội viên), quyền riêng tư, bền vững với dòng hỏng, hiệu năng.

Chấp nhận theo PR #22 (ARCHITECT 31/10, không FAIL): SĐT đầy đủ trong nhật ký (chỉ Admin xem); màn chỉ hiện người làm
Admin / Nhân viên / Hệ thống / Hội viên (T-042: chỉ dòng hội viên tự đổi hạng hiện; tự sửa hồ sơ, ảnh không hiện); "Thu cả đơn" hiện thành từng dòng "Thu tiền" theo khối.
"""

import datetime as dt
import importlib
import json
import re
import time
import uuid

import pytest
from sqlalchemy import text

from app.core.config import settings
from app.core.db import engine
from tests.conftest import API, _client, idem, sign_in

t15 = importlib.import_module("tests.test_qa_T-015")
t16 = importlib.import_module("tests.test_qa_T-016")
t19 = importlib.import_module("tests.test_qa_T-019")
t8 = importlib.import_module("tests.test_qa_T-008")
sepay = t8.sepay
made = t15.made

LOG = f"{API}/admin/audit-log"
M = f"{API}/members"
PW = "Hv-Moi-Pass-1"


async def q(sql: str, **params):
    async with engine.begin() as conn:
        return (await conn.execute(text(sql), params)).mappings().all()


async def x(sql: str, **params) -> None:
    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


async def purge(prefix: str) -> None:
    """Nhật ký không xóa được (trigger giữ 12 tháng); test tự tạo dòng giả nên tạm tắt trigger để dọn, rồi bật lại."""
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_delete_retention"))
        try:
            await conn.execute(
                text("DELETE FROM audit_log WHERE entity_code LIKE :p"), {"p": prefix + "%"}
            )
        finally:
            await conn.execute(
                text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_delete_retention")
            )


def today() -> dt.date:
    return dt.datetime.now(settings.tz).date()


async def entries(client, **params) -> list[dict]:
    r = await client.get(LOG, params={"size": 100, **params})
    assert r.status_code == 200, r.text
    return r.json()["items"]


def rows_for(items: list[dict], action: str, code: str | None = None) -> list[dict]:
    return [
        i for i in items if i["action"] == action and (code is None or i["target"]["code"] == code)
    ]


def latest(items: list[dict], action: str, code: str | None = None) -> dict:
    """Dòng mới nhất (danh sách trả mới trước). Nhật ký không xóa được và mã HV/booking của test bị dùng lại."""
    found = rows_for(items, action, code)
    assert found, (action, code)
    return found[0]


def change(entry: dict, field: str) -> dict:
    return next(c for c in entry["changes"] if c["field"] == field)


# ============================================================ quyền (chỉ Admin) + API chỉ đọc


async def test_only_admin_can_read_staff_customer_anonymous_rejected(admin, staff, customer, anon):
    for path in (LOG, f"{LOG}/catalog"):
        assert (await admin.get(path)).status_code == 200
        r = await staff.get(path)
        assert r.status_code == 403 and r.json()["detail"]["code"] == "E-AUTH-2", (path, r.text)
        assert (await customer.get(path)).status_code in (401, 403)
        assert (await anon.get(path)).status_code == 401


async def test_hội_viên_session_cannot_read_the_log(admin, made):
    c, _ = await t16.member_login(admin, made)
    assert (await c.get(LOG)).status_code in (401, 403)
    assert (await c.get(f"{LOG}/catalog")).status_code in (401, 403)


async def test_log_is_read_only_no_write_routes(admin):
    for method in ("post", "put", "patch", "delete"):
        for path in (LOG, f"{LOG}/1", f"{LOG}/catalog"):
            r = await getattr(admin, method)(path, headers=idem())
            assert r.status_code in (404, 405, 422), (method, path, r.status_code)
    spec = await admin.get(f"{API}/openapi.json")
    if spec.status_code == 200:
        for path, ops in spec.json()["paths"].items():
            if path.startswith("/api/v1/admin/audit-log") or path.startswith("/admin/audit-log"):
                assert set(ops) <= {"get"}, (path, set(ops))


async def test_responses_leak_no_secret_fields(admin):
    r = await admin.get(LOG, params={"size": 100})
    body = r.text.lower()
    for secret in (
        "hashed_password",
        "password_hash",
        "token_version",
        "webhook_secret",
        "refresh_token",
        "admin_session",
    ):
        assert secret not in body, secret
    assert set(r.json()) == {"items", "total", "page", "page_size", "date_from", "date_to"}


# ============================================================ khoảng ngày (BR-012)


async def test_default_range_is_the_last_7_days_including_today(admin):
    r = (await admin.get(LOG)).json()
    assert r["date_to"] == today().isoformat()
    assert r["date_from"] == (today() - dt.timedelta(days=6)).isoformat()
    assert r["page"] == 1 and r["page_size"] == 50


async def test_range_boundaries_inclusive_and_row_at_edges(admin):
    day = today() - dt.timedelta(days=3)
    tz = settings.tz
    first = dt.datetime.combine(day, dt.time(0, 0, 0), tz)
    last = dt.datetime.combine(day, dt.time(23, 59, 59), tz)
    nxt = dt.datetime.combine(day + dt.timedelta(days=1), dt.time(0, 0, 0), tz)
    tag = "QA-EDGE-" + uuid.uuid4().hex[:6]
    for label, at in (("first", first), ("last", last), ("next", nxt)):
        await x(
            "INSERT INTO audit_log (at, actor_type, actor_id, actor_label, action, entity_type, entity_code, detail) "
            "VALUES (:at, 'admin', NULL, 'Admin', 'auth.logout', 'user', :c, '{}'::jsonb)",
            at=at, c=f"{tag}-{label}",
        )  # fmt: skip
    got = await entries(admin, **{"from": day.isoformat(), "to": day.isoformat()})
    codes = {i["target"]["code"] for i in got} | {i["target"]["name"] for i in got}
    ours = {c for c in codes if c and c.startswith(tag)}
    assert ours == {f"{tag}-first", f"{tag}-last"}, (
        "00:00:00 and 23:59:59 of the day are in; the next midnight is out"
    )


@pytest.mark.parametrize(
    "params",
    [
        {"from": "2099-01-01"},
        {"to": "2099-01-01"},
        {"from": "2026-10-20", "to": "2026-10-10"},
        {"from": "1999-01-01"},
    ],
)
async def test_invalid_ranges_are_e_audit_1(admin, params):
    r = await admin.get(LOG, params=params)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-AUDIT-1", r.text


async def test_twelve_month_limit_and_malformed_dates(admin):
    cat = (await admin.get(f"{LOG}/catalog")).json()
    ok = await admin.get(LOG, params={"from": cat["min_date"], "to": cat["max_date"]})
    assert ok.status_code == 200, "exactly the catalog bounds are accepted"
    older = (dt.date.fromisoformat(cat["min_date"]) - dt.timedelta(days=1)).isoformat()
    r = await admin.get(LOG, params={"from": older})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-AUDIT-1"
    for bad in ("2026-13-45", "abc", "31/10/2026", "2026-10-3x"):
        assert (await admin.get(LOG, params={"from": bad})).status_code == 422, bad


# ============================================================ lọc người làm / loại thao tác


async def test_actor_filter_and_unknown_actor(admin, staff, anon, made, sepay):
    court = (await t8.court(admin))["code"]
    m = await t15.add_ok(staff, made)
    co = await t8.make_checkout(anon, t8.slots(court, 9), ph=t8.phone())
    await t8.pay(anon, co)
    for actor in ("admin", "staff", "system"):
        got = await entries(admin, actor=actor)
        assert got and all(i["actor"] == actor for i in got), actor
    assert any(i["target"]["code"] == m["member_code"] for i in await entries(admin, actor="staff"))
    assert any(
        i["target"]["code"] == co["order_code"] for i in await entries(admin, actor="system")
    )
    for bad in ("web", "root", "", "Customer"):
        assert (await admin.get(LOG, params={"actor": bad})).status_code == 422, bad


async def test_action_filter_each_catalog_type_returns_only_it(admin, staff, made):
    await t15.add_ok(admin, made)
    cat = (await admin.get(f"{LOG}/catalog")).json()
    keys = [t["key"] for g in cat["groups"] for t in g["types"]]
    assert len(keys) == len(set(keys)) > 10
    for key in keys:
        r = await admin.get(LOG, params={"action": key, "size": 100})
        assert r.status_code == 200, (key, r.text)
        labels = {i["action_label"] for i in r.json()["items"]}
        assert len(labels) <= 1, (key, labels)
    got = await entries(admin, action="member.create")
    assert got and {i["action"] for i in got} == {"member.create"}


@pytest.mark.parametrize(
    "bad",
    [
        "nope",
        "member.",
        "MEMBER.CREATE",
        "member.create' OR '1'='1",
        "member.create; DROP TABLE audit_log; --",
        "%",
        "x" * 61,
        "../../etc/passwd",
    ],
)
async def test_unknown_or_malicious_action_is_rejected_cleanly(admin, bad):
    r = await admin.get(LOG, params={"action": bad})
    assert r.status_code == 422, (bad, r.status_code, r.text[:120])
    assert r.status_code != 500
    assert (await q("SELECT count(*) AS n FROM audit_log"))[0]["n"] >= 0, "table still there"


async def test_actor_and_action_filters_combine(admin, staff, made):
    await t15.add_ok(admin, made)
    await t15.add_ok(staff, made)
    both = await entries(admin, actor="staff", action="member.create")
    assert both and all(i["actor"] == "staff" and i["action"] == "member.create" for i in both)
    none = await entries(admin, actor="system", action="member.create")
    assert none == []


# ============================================================ sắp xếp + phân trang


async def test_sort_directions_and_stable_order(admin, made):
    for _ in range(4):
        await t15.add_ok(admin, made)
    desc = await entries(admin, action="member.create", sort="at_desc")
    asc = await entries(admin, action="member.create", sort="at_asc")
    # Nhật ký không xóa được nên có thể > 100 dòng: so với cực trị theo thời điểm trong DB
    lo, hi = (
        await q("SELECT min(at) AS lo, max(at) AS hi FROM audit_log WHERE action='member.create'")
    )[0].values()
    parse = dt.datetime.fromisoformat
    assert parse(desc[0]["at"]) == hi and parse(asc[0]["at"]) == lo
    assert [i["at"] for i in desc] == sorted((i["at"] for i in desc), reverse=True)
    assert [i["at"] for i in asc] == sorted(i["at"] for i in asc)
    default = await entries(admin, action="member.create")
    assert [i["id"] for i in default] == [i["id"] for i in desc], "default = newest first"
    assert (await admin.get(LOG, params={"sort": "name_asc"})).status_code == 422


@pytest.mark.parametrize(
    ("size", "ok"),
    [
        (20, True),
        (50, True),
        (100, True),
        (10, False),
        (0, False),
        (200, False),
        (-5, False),
        ("abc", False),
        (51, False),
    ],
)
async def test_page_size_only_20_50_100(admin, size, ok):
    r = await admin.get(LOG, params={"size": size})
    assert (r.status_code == 200) == ok, (size, r.status_code)
    if ok:
        j = r.json()
        assert j["page_size"] == int(size) and len(j["items"]) <= int(size)


async def test_pagination_has_no_overlap_or_gap_and_bounds(admin, made):
    tag = "QA-PAGE-" + uuid.uuid4().hex[:5]
    for i in range(45):
        await x(
            "INSERT INTO audit_log (at, actor_type, actor_label, action, entity_type, entity_code, detail) "
            "VALUES (now(), 'admin', 'Admin', 'auth.logout', 'user', :c, '{}'::jsonb)",
            c=f"{tag}-{i:02d}",
        )  # cùng một thời điểm → id phân hòa
    seen: list[int] = []
    for page in (1, 2, 3):
        r = (
            await admin.get(LOG, params={"action": "auth.logout", "size": 20, "page": page})
        ).json()
        seen += [i["id"] for i in r["items"]]
    assert len(seen) == len(set(seen)), "no row repeated across pages"
    total = (await admin.get(LOG, params={"action": "auth.logout", "size": 20})).json()["total"]
    assert total >= 45
    beyond = (
        await admin.get(LOG, params={"action": "auth.logout", "size": 20, "page": 10000})
    ).json()
    assert beyond["items"] == [] and beyond["total"] == total
    for bad in (0, -1, 10001, "x"):
        assert (await admin.get(LOG, params={"page": bad})).status_code == 422, bad
    await purge(tag)


# ============================================================ nội dung dòng: T-019 mã đơn / mã khối


async def test_t019_counter_order_one_row_per_block_with_child_code_target(admin, staff):
    a, b = await t19.courts(admin, 2)
    order = await t19.counter_ok(
        staff, [t19.block(a, t19.h(0), t19.h(1)), t19.block(b, t19.h(0), t19.h(1))]
    )
    codes = [bk["code"] for bk in order["bookings"]]
    got = await entries(admin, action="booking.counter.create")
    for c in codes:
        row = latest(got, "booking.counter.create", c)
        assert (
            row["actor"] == "staff"
            and row["actor_label"] == "Nhân viên"
            and re.fullmatch(r"NV\d{3,}", row["actor_code"] or "")
        )
        assert row["actor_name"], "tên nhân viên lúc làm"
        assert [ch["field"] for ch in row["changes"]] == ["Sân", "Khung giờ", "Khách"]
        assert all(ch["before"] is None for ch in row["changes"]), "tạo mới: trước = (trống)"
        assert re.fullmatch(
            r"\d{2}:00–\d{2}:00 \d{2}/\d{2}/\d{4}", change(row, "Khung giờ")["after"]
        ), change(row, "Khung giờ")
    sân = {change(rows_for(got, "booking.counter.create", c)[0], "Sân")["after"] for c in codes}
    assert len(sân) == 2, "mỗi khối một sân riêng"
    stored = await q(
        "SELECT detail::text AS d FROM audit_log WHERE action='booking.counter.create' AND entity_code = ANY(:c)",
        c=codes,
    )
    assert all(order["order_code"] in r["d"] for r in stored), "mã đơn có trong chi tiết lưu (AC8)"


async def test_t019_collect_whole_order_shows_one_thu_tien_row_per_block_and_no_extra_type(
    admin, staff
):
    a, b = await t19.courts(admin, 2)
    order = await t19.counter_ok(
        admin, [t19.block(a, t19.h(0), t19.h(1)), t19.block(b, t19.h(0), t19.h(1))]
    )
    r = await admin.post(
        f"{API}/booking/orders/{order['order_code']}/collect",
        json={"method": "cash"},
        headers=idem(),
    )
    assert r.status_code == 200
    got = await entries(admin, action="payment.collect")
    for bk in order["bookings"]:
        row = latest(got, "payment.collect", bk["code"])
        assert row["action_label"] == "Thu tiền"
        assert change(row, "Thanh toán") == {
            "field": "Thanh toán",
            "before": "Chưa thanh toán",
            "after": "Đã thanh toán",
        }
        assert change(row, "Phương thức")["after"] == "Tiền mặt"
    assert (await admin.get(LOG, params={"action": "payment.collect_order"})).status_code == 422, (
        "không có loại 'thu cả đơn' riêng (chấp nhận)"
    )
    assert not any(i["action"] == "payment.collect_order" for i in await entries(admin))


async def test_t019_online_payment_row_by_system_targets_the_order_code(admin, anon, sepay):
    court = (await t8.court(admin))["code"]
    co = await t8.make_checkout(anon, t8.slots(court, 9, 10, 14), ph=t8.phone())
    await t8.pay(anon, co)
    got = await entries(admin, actor="system")
    row = latest(got, "payment.collect", co["order_code"])
    assert (
        row["actor"] == "system"
        and row["actor_label"] == "Hệ thống"
        and row["action_label"] == "Thu tiền"
    )
    assert (
        change(row, "Phương thức")["after"] == "QR"
        and change(row, "Thanh toán")["after"] == "Đã thanh toán"
    )
    assert row["target"]["name"] == "QA Khách Web"


async def test_failed_or_conflicting_orders_leave_no_row(admin):
    a, b = await t19.courts(admin, 2)
    await t19.counter_ok(admin, [t19.block(b, t19.h(0), t19.h(1))])
    before = (
        await q("SELECT count(*) AS n FROM audit_log WHERE action IN ('booking.counter.create')")
    )[0]["n"]
    r = await t19.counter(
        admin, [t19.block(a, t19.h(0), t19.h(1)), t19.block(b, t19.h(0), t19.h(1))]
    )
    assert r.status_code == 409
    after = (
        await q("SELECT count(*) AS n FROM audit_log WHERE action IN ('booking.counter.create')")
    )[0]["n"]
    assert after == before, "all-or-nothing: no audit for a refused order"


# ============================================================ nội dung dòng: T-020 sửa hội viên, T-016 tự sửa + ảnh


async def test_t020_member_create_update_temp_rows_before_after(admin, staff, made):
    m = await t15.add_ok(admin, made, tier="Trung bình")
    path = f"{M}/{m['member_code']}"
    assert (
        await t15.patch_m(staff, path, {"tier": "Khá", "full_name": f"{t15.tag()} Tên Mới"})
    ).status_code == 200
    got = await entries(admin)
    create = latest(got, "member.create", m["member_code"])
    assert (
        create["actor"] == "admin"
        and create["actor_label"] == "Admin"
        and create["actor_name"] is None
    )
    assert (
        change(create, "Trình độ")["before"] is None
        and change(create, "Trình độ")["after"] == "Trung bình"
    )
    upd = latest(got, "member.update", m["member_code"])
    assert upd["actor"] == "staff" and upd["actor_code"]
    assert change(upd, "Trình độ") == {"field": "Trình độ", "before": "Trung bình", "after": "Khá"}
    assert change(upd, "Họ tên")["before"] == m["full_name"] and change(upd, "Họ tên")[
        "after"
    ].endswith("Tên Mới")
    assert not any(c["before"] == c["after"] for c in upd["changes"]), "ô không đổi không hiện"
    # tên đối tượng là bản chụp lúc thao tác (tên cũ ở dòng tạo)
    assert create["target"]["name"] == m["full_name"]


async def test_t020_noop_edit_conflicts_and_replays_do_not_write_rows(admin, made):
    m = await t15.add_ok(admin, made, tier="Khá")
    path = f"{M}/{m['member_code']}"
    base = (
        await q(
            "SELECT count(*) AS n FROM audit_log WHERE action IN ('member.update','member.create') AND entity_code=:c",
            c=m["member_code"],
        )
    )[0]["n"]
    v = (await admin.get(path)).json()["version"]
    assert (
        await t15.patch_m(admin, path, {"tier": "Khá"}, version=v)
    ).status_code == 200  # không đổi
    assert (
        await t15.patch_m(admin, path, {"tier": "Yếu"}, version=v + 99)
    ).status_code == 409  # lệch version
    phone = t15.random_phone()
    made.append(phone)
    base_id = (await q("SELECT coalesce(max(id), 0) AS i FROM audit_log"))[0]["i"]
    key = {"Idempotency-Key": str(uuid.uuid4())}
    body = {"full_name": f"{t15.tag()} Lặp", "phone": phone}
    r1 = await admin.post(M, json=body, headers=key)
    r2 = await admin.post(M, json=body, headers=key)
    assert r1.status_code == r2.status_code == 201
    dup = await admin.post(M, json={"full_name": "x", "phone": phone}, headers=idem())
    assert dup.status_code == 409
    after = (
        await q(
            "SELECT count(*) AS n FROM audit_log WHERE action IN ('member.update','member.create') AND entity_code=:c",
            c=m["member_code"],
        )
    )[0]["n"]
    assert after == base, "no-op / stale / failed saves write nothing"
    creates = await q(
        "SELECT count(*) AS n FROM audit_log WHERE id > :b AND action='member.create' AND detail::text LIKE :p",
        b=base_id, p=f"%{phone}%",
    )  # fmt: skip
    assert creates[0]["n"] == 1, "gửi lại cùng Idempotency-Key chỉ một dòng nhật ký"


async def test_t016_member_self_edit_and_avatar_are_not_shown_and_email_is_never_exposed(
    admin, made
):
    c, m = await t16.member_login(admin, made, tier="Khá")
    mail = f"{t16.tag().lower()}@example.com"
    cur = await t16.me(c)
    assert (
        await t16.save(c, cur, nickname="Gió", email=mail, tier="Bán chuyên")  # T-042: tự đổi Hạng
    ).status_code == 200
    assert (await t16.upload(c, t16.png(), size=200)).status_code == 200
    stored = await q(
        "SELECT action, detail::text AS d, actor_type FROM audit_log WHERE entity_code=:c AND action LIKE 'member.%'",
        c=m["member_code"],
    )
    assert any(r["action"] == "member.self_update" for r in stored)
    assert all(mail not in r["d"] for r in stored), (
        "email không nằm trong nhật ký (che hoặc không ghi)"
    )
    assert any(
        re.search(r"[a-z0-9]\*\*\*@example\.com", r["d"])
        for r in stored
        if r["action"] == "member.self_update"
    )
    for r in stored:
        if r["action"] in ("member.self_update", "member.avatar_update"):
            assert r["actor_type"] not in ("admin", "staff", "system"), r["actor_type"]
    r = await admin.get(LOG, params={"size": 100})
    assert mail not in r.text and mail.upper() not in r.text.upper()
    shown = {i["action"] for i in r.json()["items"]}
    assert not shown & {"member.self_update", "member.avatar_update", "member.avatar_delete"}, (
        "chấp nhận: hội viên tự sửa không hiện ở màn"
    )
    # T-042: riêng việc hội viên tự đổi Hạng thì hiện, người làm = Hội viên
    assert "member.tier_self_change" in shown
    mine = [
        i
        for i in r.json()["items"]
        if i["action"] == "member.tier_self_change" and i["target"]["code"] == m["member_code"]
    ]
    assert mine and mine[0]["actor"] == "customer" and mine[0]["actor_label"] == "Hội viên"


# ============================================================ danh tính người làm + đăng nhập/đăng xuất


async def test_staff_name_snapshot_and_code_link(admin, staff, made):
    m = await t15.add_ok(staff, made)
    row = latest(await entries(admin, actor="staff"), "member.create", m["member_code"])
    assert row["actor_code"] and re.fullmatch(r"NV\d{3,}", row["actor_code"])
    name = row["actor_name"]
    uid = (await q("SELECT id FROM users WHERE staff_code=:c", c=row["actor_code"]))[0]["id"]
    await x("UPDATE users SET full_name='Tên Đã Đổi QA' WHERE id=:i", i=uid)
    again = latest(await entries(admin, actor="staff"), "member.create", m["member_code"])
    assert again["actor_name"] == name, (
        "tên hiển thị là bản chụp lúc làm, đổi tên NV sau đó không đổi dòng cũ"
    )
    await x("UPDATE users SET full_name=:n WHERE id=:i", n=name, i=uid)


async def test_login_logout_rows_have_no_values_and_never_the_password(admin):
    c = _client()
    assert (
        await sign_in(c, settings.FIRST_ADMIN_PHONE, settings.FIRST_ADMIN_PASSWORD)
    ).status_code == 200
    await c.post(f"{API}/admin/auth/logout", headers=idem())
    got = await entries(admin, actor="admin")
    login = rows_for(got, "auth.login_success")
    assert login and all(i["changes"] == [] for i in login)
    assert settings.FIRST_ADMIN_PASSWORD not in json.dumps(got)


# ============================================================ nhật ký quyền riêng tư: SĐT đầy đủ là chấp nhận, mật khẩu/token thì không


async def test_phone_appears_only_in_known_fields_and_never_passwords(admin, made):
    m = await t15.add_ok(admin, made)
    got = await entries(admin)
    create = latest(got, "member.create", m["member_code"])
    phones = [c["after"] for c in create["changes"] if c["field"] == "SĐT"]
    assert phones == [m["phone"]], "chấp nhận: SĐT đầy đủ (BR-007, chỉ Admin xem)"
    text_all = json.dumps(got, ensure_ascii=False)
    assert "Hv-Moi-Pass" not in text_all and PW not in text_all
    assert m["phone"] not in json.dumps(
        {k: v for k, v in create.items() if k not in ("changes", "target")}
    ), "SĐT không rò ra các trường khác"


# ============================================================ dòng hỏng / lạ không làm vỡ trang


def jsonb(value: str) -> str:
    """Literal jsonb cho SQL: bọc nháy đơn, nhân đôi nháy đơn bên trong."""
    return "'" + value.replace("'", "''") + "'::jsonb"


@pytest.mark.parametrize(
    "detail",
    [
        pytest.param(jsonb('"just a string"'), id="detail-is-a-string"),
        pytest.param(jsonb("[1,2,3]"), id="detail-is-an-array"),
        pytest.param(jsonb('{"target": 5, "changes": "x"}'), id="target-and-changes-wrong-type"),
        pytest.param(
            jsonb(
                '{"target": {"code": 1}, "changes": [{"field": 1}, {"from": "a", "to": "b"}, 7, null]}'
            ),
            id="changes-items-wrong",
        ),
        pytest.param(
            jsonb('{"changes": [{"field": "Hạng", "before": {"x": 1}, "after": [1]}]}'),
            id="values-are-objects",
        ),
        pytest.param(jsonb("{}"), id="empty-object"),
    ],
)
async def test_broken_legacy_rows_never_break_the_list(admin, detail):
    tag = "QA-BROKEN-" + uuid.uuid4().hex[:6]
    await x(
        "INSERT INTO audit_log (at, actor_type, actor_label, action, entity_type, entity_code, detail) "
        f"VALUES (now(), 'admin', 'Admin', 'member.update', 'customer', :c, {detail})",
        c=tag,
    )
    try:
        r = await admin.get(LOG, params={"size": 100, "action": "member.update"})
        assert r.status_code == 200, r.text[:200]
        assert (await admin.get(LOG, params={"size": 100})).status_code == 200
    finally:
        await purge(tag)


async def test_unknown_action_and_web_actor_rows_are_not_shown(admin):
    tag = "QA-HIDDEN-" + uuid.uuid4().hex[:6]
    base = "INSERT INTO audit_log (at, actor_type, actor_label, action, entity_type, entity_code, detail) VALUES (now(), :a, 'X', :act, 'x', :c, '{}'::jsonb)"
    try:
        await x(base, a="admin", act="some.unknown.action", c=tag + "-unknown")
        await x(base, a="web", act="member.update", c=tag + "-web")
        # T-042: người làm "customer" chỉ hiện với thao tác trong danh mục; thao tác khác của khách vẫn ẩn
        await x(base, a="customer", act="member.self_update", c=tag + "-cust")
        got = await entries(admin, action="member.update")
        shown = {i["target"]["code"] for i in got}
        assert not {tag + "-web", tag + "-cust", tag + "-unknown"} & shown
        assert tag + "-cust" not in {
            i["target"]["code"] for i in await entries(admin, actor="customer")
        }
        assert not any(i["target"]["code"] == tag + "-unknown" for i in await entries(admin))
    finally:
        await purge(tag)


async def test_log_rows_cannot_be_updated_deleted_or_truncated_at_db_level(admin, made):
    m = await t15.add_ok(admin, made)
    row = (
        await q(
            "SELECT id FROM audit_log WHERE action='member.create' AND entity_code=:c ORDER BY id DESC LIMIT 1",
            c=m["member_code"],
        )
    )[0]["id"]
    for sql in (
        "UPDATE audit_log SET actor_label='Hacker' WHERE id=:i",
        "DELETE FROM audit_log WHERE id=:i",
        "TRUNCATE audit_log",
    ):
        with pytest.raises(Exception, match="audit_log|cannot|immutable|retention"):
            await x(sql, i=row)
    assert (await q("SELECT actor_label FROM audit_log WHERE id=:i", i=row))[0][
        "actor_label"
    ] == "Admin"


async def test_hostile_text_is_returned_as_plain_data(admin, made):
    evil = "<img src=x onerror=alert(1)>" + t15.tag()
    m = await t15.add_ok(admin, made, name=evil)
    got = await entries(admin)
    row = latest(got, "member.create", m["member_code"])
    assert row["target"]["name"] == m["full_name"], (
        "tên được trả nguyên văn như dữ liệu (FE thoát khi hiển thị)"
    )


# ============================================================ hiệu năng


async def test_list_stays_fast_with_20000_rows(admin):
    tag = "QA-PERF-" + uuid.uuid4().hex[:5]
    await x(
        "INSERT INTO audit_log (at, actor_type, actor_label, action, entity_type, entity_code, detail) "
        "SELECT now() - (g || ' seconds')::interval, 'admin', 'Admin', 'member.update', 'customer', :t || g, "
        '\'{"target": {"code": "HV0001", "name": "QA"}, "changes": [{"field": "Hạng", "before": "Khá", "after": "Yếu"}]}\'::jsonb '
        "FROM generate_series(1, 5000) g",
        t=tag,
    )
    try:
        timings = {}
        for name, params in (
            ("default", {}),
            ("size100", {"size": 100}),
            ("action", {"action": "member.update", "size": 100}),
            ("asc_page50", {"sort": "at_asc", "page": 50, "size": 100}),
            ("actor", {"actor": "admin"}),
        ):
            t0 = time.perf_counter()
            r = await admin.get(LOG, params=params)
            timings[name] = time.perf_counter() - t0
            assert r.status_code == 200
        print("T-022 timings", {k: round(v, 2) for k, v in timings.items()})
        assert max(timings.values()) < 3, timings
    finally:
        await purge(tag)
