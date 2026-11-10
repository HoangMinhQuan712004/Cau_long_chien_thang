"""T-063: sửa ngày Lễ/Tết (PATCH /booking/special-days/{id}) – chồng mục khác -> E-CFG-8, bỏ qua
chính nó, khác năm -> 422, giá booking đã có không đổi, quyền, Idempotency-Key, audit + outbox.
"""

import pytest
from sqlalchemy import delete, select

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.core.permissions import Perm
from app.modules.auth.models import RolePermission
from app.modules.booking_engine.models import Booking, OutboxEvent
from tests.conftest import idem
from tests.helpers_booking import BK, book, new_court, random_phone, safe_hour, temp, today


async def add(admin, date_from: str, name: str, date_to: str | None = None) -> dict:
    r = await admin.post(
        f"{BK}/special-days",
        json={"date_from": date_from, "date_to": date_to, "name": name},
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def patch(client, special_id: int, body: dict, headers: dict | None = None):
    return await client.patch(
        f"{BK}/special-days/{special_id}", json=body, headers=headers or idem()
    )


async def remove(admin, *rows: dict) -> None:
    for row in rows:
        await admin.delete(f"{BK}/special-days/{row['id']}", headers=idem())


async def test_update_dates_and_name_with_overlap_rules(admin):
    """AC2–AC4: sửa ngày / tên; chồng mục khác -> E-CFG-8 giữ nguyên; chính nó không tính chồng."""
    tet = await add(admin, "2036-01-28", "Tết 2036", "2036-02-01")
    other = await add(admin, "2036-04-30", "Lễ 30/4")
    try:
        # Chỉ đổi tên, giữ ngày -> không chồng với chính nó
        r = await patch(
            admin, tet["id"], {"date_from": "2036-01-28", "date_to": "2036-02-01", "name": "Tết"}
        )
        assert r.status_code == 200, r.text
        assert r.json() == {**tet, "name": "Tết"}
        # Dời một phần lên chính khoảng cũ (chồng với chính nó) -> được
        r = await patch(
            admin, tet["id"], {"date_from": "2036-01-30", "date_to": "2036-02-03", "name": "Tết"}
        )
        assert r.status_code == 200, r.text
        assert (r.json()["date_from"], r.json()["date_to"]) == ("2036-01-30", "2036-02-03")

        # Chồng mục khác -> 409, dữ liệu giữ nguyên
        r = await patch(
            admin, tet["id"], {"date_from": "2036-04-29", "date_to": "2036-05-01", "name": "X"}
        )
        assert r.status_code == 409
        assert r.json()["detail"] == {
            "code": "E-CFG-8",
            "message": "Ngày 30/04 đã nằm trong Lễ 30/4.",
        }
        listed = (await admin.get(f"{BK}/special-days", params={"year": 2036})).json()
        assert [(d["date_from"], d["date_to"], d["name"]) for d in listed] == [
            ("2036-01-30", "2036-02-03", "Tết"),
            ("2036-04-30", "2036-04-30", "Lễ 30/4"),
        ]

        # Validate như POST: vắt qua năm, ngược, tên rỗng -> 422
        for body in (
            {"date_from": "2036-12-31", "date_to": "2037-01-01", "name": "Qua năm"},
            {"date_from": "2036-05-03", "date_to": "2036-05-02", "name": "Ngược"},
            {"date_from": "2036-06-01", "name": ""},
        ):
            assert (await patch(admin, tet["id"], body)).status_code == 422, body
        # Đổi sang năm khác (cả khoảng trong năm đó) -> được; danh sách năm cũ không còn
        r = await patch(admin, other["id"], {"date_from": "2037-04-30", "name": "Lễ 30/4 2037"})
        assert r.status_code == 200, r.text
        listed = (await admin.get(f"{BK}/special-days", params={"year": 2037})).json()
        assert [d["id"] for d in listed] == [other["id"]]
        r = await patch(admin, 999_999_999, {"date_from": "2036-06-01", "name": "Không có"})
        assert r.status_code == 404
    finally:
        await remove(admin, tet, other)


async def test_update_audits_before_after_and_emits_event(admin):
    row = await add(admin, "2038-09-02", "Quốc khánh")
    try:
        r = await patch(
            admin, row["id"], {"date_from": "2038-09-01", "date_to": "2038-09-02", "name": "QK"}
        )
        assert r.status_code == 200, r.text
        async with SessionLocal() as s:
            [log] = list(
                await s.scalars(
                    select(AuditLog).where(
                        AuditLog.action == "config.special_day.update",
                        AuditLog.entity_code == str(row["id"]),
                    )
                )
            )
            events = list(
                await s.scalars(
                    select(OutboxEvent).where(
                        OutboxEvent.event_type == "config.special_day.updated"
                    )
                )
            )
        assert {(c["field"], c["before"], c["after"]) for c in log.detail["changes"]} == {
            ("Từ ngày", "2038-09-02", "2038-09-01"),
            ("Tên", "Quốc khánh", "QK"),
        }
        [event] = [e for e in events if e.payload["id"] == row["id"]]
        assert event.payload["before"]["date_from"] == "2038-09-02"
        assert event.payload["after"] == {
            "date_from": "2038-09-01",
            "date_to": "2038-09-02",
            "name": "QK",
        }
        # Không đổi gì -> không thêm dòng nhật ký
        r = await patch(
            admin, row["id"], {"date_from": "2038-09-01", "date_to": "2038-09-02", "name": "QK"}
        )
        assert r.status_code == 200
        async with SessionLocal() as s:
            n = len(
                list(
                    await s.scalars(
                        select(AuditLog).where(
                            AuditLog.action == "config.special_day.update",
                            AuditLog.entity_code == str(row["id"]),
                        )
                    )
                )
            )
        assert n == 1
    finally:
        await remove(admin, row)


async def test_existing_booking_keeps_its_price_and_new_quote_follows(admin):
    """AC5: dời ngày Lễ lên ngày đã có booking -> booking giữ giá; báo giá mới theo giá Lễ."""
    court = await new_court(admin)
    day = today()  # đặt quầy chỉ cho hôm nay
    hour = await safe_hour()
    quote = {
        "resource_code": court["code"],
        "date": day.isoformat(),
        "start_hour": hour,
        "end_hour": hour + 1,
    }
    before = (await admin.post(f"{BK}/quote", json=quote)).json()
    if before["day_type"] == "holiday":
        pytest.skip("hôm nay đã là ngày Lễ có sẵn")
    r = await book(admin, court["code"], hour, customer=temp("Giá Cũ", random_phone()), day=day)
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    row = await add(admin, "2041-06-15", "Lễ thử")  # ngày trống, sửa sang ngày đã đặt
    try:
        r = await patch(admin, row["id"], {"date_from": day.isoformat(), "name": "Lễ thử"})
        assert r.status_code == 200, r.text
        async with SessionLocal() as s:
            amount = await s.scalar(select(Booking.amount).where(Booking.code == code))
        assert amount == before["total_amount"]
        after = (await admin.post(f"{BK}/quote", json=quote)).json()
        assert after["day_type"] == "holiday"
    finally:
        await remove(admin, row)


async def test_permission_and_idempotency(admin, staff, anon):
    """AC6: không có booking.config.manage -> 403; gửi lại cùng key -> không áp hai lần."""
    row = await add(admin, "2040-03-08", "Ngày thử")
    perm = Perm.BOOKING_CONFIG_MANAGE.value
    try:
        body = {"date_from": "2040-03-09", "name": "Ngày thử 2"}
        assert (await patch(anon, row["id"], body)).status_code == 401
        async with SessionLocal() as s:
            had = await s.scalar(
                select(RolePermission).where(
                    RolePermission.role == "staff", RolePermission.perm == perm
                )
            )
            await s.execute(
                delete(RolePermission).where(
                    RolePermission.role == "staff", RolePermission.perm == perm
                )
            )
            await s.commit()
        try:
            r = await patch(staff, row["id"], body)
            assert r.status_code == 403, r.text
        finally:
            if had is not None:
                async with SessionLocal() as s:
                    s.add(RolePermission(role="staff", perm=perm))
                    await s.commit()

        headers = idem()
        first = await patch(admin, row["id"], body, headers=headers)
        assert first.status_code == 200, first.text
        # Gửi lại cùng key, cùng body -> trả kết quả lần đầu, không áp lần hai
        replay = await patch(admin, row["id"], body, headers=headers)
        assert replay.status_code == 200 and replay.json() == first.json()
        assert "idempotent-replayed" in {k.lower() for k in replay.headers}
        async with SessionLocal() as s:
            n = len(
                list(
                    await s.scalars(
                        select(AuditLog).where(
                            AuditLog.action == "config.special_day.update",
                            AuditLog.entity_code == str(row["id"]),
                        )
                    )
                )
            )
        assert n == 1
        evil = await admin.patch(
            f"{BK}/special-days/{row['id']}",
            json=body,
            headers={**idem(), "Origin": "https://evil.example"},
        )
        assert evil.status_code == 403
    finally:
        await remove(admin, row)
