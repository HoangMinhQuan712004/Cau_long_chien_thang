"""T-006 phần 3: thu tiền mặt, Không thu được, Lịch sử giao dịch."""

import asyncio
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.booking_engine.models import Booking, BookingOrder, Resource
from tests.conftest import API, idem, is_staff_label
from tests.helpers_booking import (
    BK,
    at,
    book,
    calendar,
    new_court,
    random_phone,
    safe_hour,
    temp,
    today,
)

FD = f"{API}/front-desk"


async def new_booking(admin, staff, customer=None, hour=None) -> dict:
    court = await new_court(admin)
    r = await book(
        staff, court["code"], hour if hour is not None else await safe_hour(), customer=customer
    )
    assert r.status_code == 201, r.text
    return r.json()


async def collect(client, code, version=1, method="cash", headers=None):
    return await client.post(
        f"{BK}/items/{code}/collect",
        json={"method": method, "version": version},
        headers=headers or idem(),
    )


async def uncollectible(client, code, reason="Khách bỏ về", version=1):
    return await client.post(
        f"{BK}/items/{code}/uncollectible",
        json={"reason": reason, "version": version},
        headers=idem(),
    )


async def audit_count(code: str, action: str) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count()).where(AuditLog.entity_code == code, AuditLog.action == action)
        )


# ------------------------------------------------------------------ thu tiền (BR-014)


async def test_collect_cash(admin, staff):
    b = await new_booking(admin, staff)
    before = (await calendar(staff))["unpaid_count"]
    r = await collect(staff, b["code"])
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["version"] == 2 and item["actions"] == []
    pay = item["payment"]
    assert (pay["payment_status"], pay["payment_method"]) == ("paid", "cash")
    assert is_staff_label(pay["collected_by"]) and pay["paid_at"]
    assert pay["amount"] == b["payment"]["amount"]
    cal = await calendar(staff)
    assert cal["unpaid_count"] == before - 1
    assert next(x for x in cal["blocks"] if x["code"] == b["code"])["payment_status"] == "paid"
    assert await audit_count(b["code"], "payment.collect") == 1

    # Trạng thái cuối: không thu lại, không đánh dấu Không thu được
    assert (await collect(staff, b["code"], version=2)).json()["detail"]["code"] == "E-012"
    r = await uncollectible(staff, b["code"], version=2)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-012"


async def test_collect_transfer_not_yet_supported(admin, staff):
    b = await new_booking(admin, staff)
    r = await collect(staff, b["code"], method="transfer")
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-PAY-0"
    r = await staff.post(
        f"{BK}/items/{b['code']}/collect",
        json={"method": "cash", "version": 1, "amount": 1},
        headers=idem(),
    )
    assert r.status_code == 422


async def test_collect_stale_version(admin, staff):
    b = await new_booking(admin, staff)
    r = await collect(staff, b["code"], version=7)
    assert r.status_code == 409
    assert r.json()["detail"] == {
        "code": "E-012",
        "message": "Booking này vừa được cập nhật ở máy khác. Vui lòng xem lại.",
    }
    r = await collect(staff, "BK-20000101-001")
    assert r.status_code == 404


async def test_collect_race_two_machines(admin, staff):
    b = await new_booking(admin, staff)
    r1, r2 = await asyncio.gather(collect(staff, b["code"]), collect(admin, b["code"]))
    assert sorted([r1.status_code, r2.status_code]) == [200, 409]
    loser = r1 if r1.status_code == 409 else r2
    assert loser.json()["detail"]["code"] == "E-012"
    assert await audit_count(b["code"], "payment.collect") == 1


async def test_collect_double_click_same_key(admin, staff):
    b = await new_booking(admin, staff)
    headers = idem()
    r1 = await collect(staff, b["code"], headers=headers)
    r2 = await collect(staff, b["code"], headers=headers)
    assert r1.status_code == r2.status_code == 200
    assert r2.json() == r1.json() and r2.headers.get("idempotent-replayed") == "true"
    assert await audit_count(b["code"], "payment.collect") == 1


# ------------------------------------------------------------------ Không thu được (BR-015)


async def test_uncollectible_keeps_slot(admin, staff):
    hour = await safe_hour()
    court = await new_court(admin)
    b = (await book(staff, court["code"], hour)).json()
    assert b["actions"] == ["collect", "uncollectible"]  # khung đang diễn ra: đã tới giờ
    for reason in ("   ", "x" * 201):
        r = await uncollectible(staff, b["code"], reason=reason)
        assert r.status_code == 422 and r.json()["detail"]["code"] == "E-001"
    r = await uncollectible(staff, b["code"], reason="  <script>alert(1)</script> ")
    assert r.status_code == 200, r.text
    pay = r.json()["payment"]
    assert pay["payment_status"] == "uncollectible"
    assert pay["uncollectible_reason"] == "<script>alert(1)</script>"
    assert is_staff_label(pay["marked_by"]) and pay["marked_at"]
    assert r.json()["actions"] == []
    # Khung không trống lại
    r = await book(staff, court["code"], hour)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-003"
    block = next(x for x in (await calendar(staff))["blocks"] if x["code"] == b["code"])
    assert block["payment_status"] == "uncollectible"
    assert await audit_count(b["code"], "payment.uncollectible") == 1


async def test_uncollectible_before_start_or_online(admin, staff):
    hour = await safe_hour()
    if hour <= 22:
        b = await new_booking(admin, staff, hour=hour + 1)
        assert b["actions"] == ["collect"]
        r = await uncollectible(staff, b["code"])
        assert r.status_code == 422 and r.json()["detail"]["code"] == "E-PAY-1"

    # Booking online (T-008 mới có API): tạo thẳng trong DB
    code = f"BK-ONL-{uuid.uuid4().hex[:6].upper()}"
    async with SessionLocal() as s:
        resource_id = await s.scalar(select(Resource.id).where(Resource.code == "S01"))
        customer = {
            "customer_ref": "x",
            "customer_kind": "temp",
            "customer_name": "Khách web",
            "customer_phone": "0900000001",
        }
        order = BookingOrder(
            tenant_id=settings.TENANT_ID,
            code=code,
            play_date=today(),
            channel="online",
            created_by_label="Khách đặt online",
            **customer,
        )
        s.add(order)
        await s.flush()
        s.add(
            Booking(
                tenant_id=settings.TENANT_ID,
                order_id=order.id,
                seq=1,
                code=f"{code}-01",
                source="online",
                resource_id=resource_id,
                play_date=today(),
                start_at=at(today(), 0),
                end_at=at(today(), 1),
                amount=100_000,
                payment_status="unpaid",
                created_by_type="web",
                created_by_label="Khách đặt online",
                **customer,
            )
        )
        await s.commit()
    code = f"{code}-01"  # mã con của khối
    item = (await staff.get(f"{BK}/items/{code}")).json()
    assert item["actions"] == ["collect"]
    r = await uncollectible(staff, code)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-PAY-1"


async def test_ticket_collect_and_uncollectible(admin, staff):
    court = await new_court(admin)
    hour = await safe_hour()
    ev = (
        await admin.post(
            f"{BK}/sessions",
            json={
                "resource_codes": [court["code"]],
                "date": today().isoformat(),
                "start_hour": hour,
                "end_hour": hour + 1,
                "name": "Giao lưu",
                "capacity": 5,
                "ticket_price": 40_000,
            },
            headers=idem(),
        )
    ).json()

    async def ticket():
        r = await staff.post(
            f"{FD}/sessions/{ev['code']}/tickets",
            json={"customer": {"member_code": "HV0012"}},
            headers=idem(),
        )
        assert r.status_code == 201, r.text
        return r.json()

    t1, t2 = await ticket(), await ticket()
    r = await collect(staff, t1["code"])
    assert r.status_code == 200 and r.json()["payment"]["amount"] == 40_000
    r = await uncollectible(staff, t2["code"])
    assert r.status_code == 200 and r.json()["payment"]["payment_status"] == "uncollectible"
    detail = (await staff.get(f"{BK}/sessions/{ev['code']}")).json()
    assert detail["taken"] == 2  # vé Không thu được vẫn chiếm chỗ
    assert {t["payment_status"] for t in detail["tickets"]} == {"paid", "uncollectible"}


# ------------------------------------------------------------------ Lịch sử giao dịch (BR-020)


async def test_transactions_filters_cards_and_paging(admin, staff):
    tag = f"TX{uuid.uuid4().hex[:6]}"
    hour = await safe_hour()
    phones = [random_phone() for _ in range(10)]
    codes = []
    for i, phone in enumerate(phones):
        court = await new_court(admin)
        r = await book(staff, court["code"], hour, customer=temp(f"{tag} khách {i}", phone))
        assert r.status_code == 201, r.text
        codes.append(r.json()["code"])
    await collect(staff, codes[0])
    await collect(staff, codes[1])
    await uncollectible(staff, codes[2])
    amount = (await staff.get(f"{BK}/items/{codes[0]}")).json()["payment"]["amount"]

    async def tx(**params):
        r = await admin.get(f"{BK}/transactions", params={"q": tag, **params})
        assert r.status_code == 200, r.text
        return r.json()

    data = await tx()
    assert data["date_to"] == today().isoformat()
    assert data["date_from"] == (today() - timedelta(days=6)).isoformat()
    assert data["total"] == 10 and data["page_size"] == 8 and len(data["rows"]) == 8
    assert data["cards"] == {
        "paid": {"amount": 2 * amount, "count": 2},
        "unpaid": {"amount": 7 * amount, "count": 7},
        "uncollectible": {"amount": amount, "count": 1},
    }
    page2 = await tx(page=2)
    assert len(page2["rows"]) == 2
    seen = [row["code"] for row in data["rows"] + page2["rows"]]
    assert sorted(seen) == sorted(codes)
    row = data["rows"][0]
    assert set(row) == {
        "kind", "code", "order_code", "play_date", "start_time", "end_time", "resource_codes",
        "customer_name", "phone", "amount", "payment_status", "payment_method", "source",
    }  # fmt: skip
    assert {row["phone"] for row in data["rows"] + page2["rows"]} == set(phones)  # SĐT đầy đủ

    assert (await tx(status="paid"))["total"] == 2
    cash = await tx(method="cash")
    assert cash["total"] == 2 and {r["payment_status"] for r in cash["rows"]} == {"paid"}
    assert (await tx(method="transfer"))["total"] == 0

    # Tìm theo mã (thường, khoảng trắng) / SĐT có dấu chấm
    r = await admin.get(f"{BK}/transactions", params={"q": f" {codes[3].lower()} "})
    assert [x["code"] for x in r.json()["rows"]] == [codes[3]]
    dotted = f"{phones[4][:4]}.{phones[4][4:7]}.{phones[4][7:]}"
    r = await admin.get(f"{BK}/transactions", params={"q": dotted})
    assert [x["code"] for x in r.json()["rows"]] == [codes[4]]
    # Lọc sân
    court_code = (await staff.get(f"{BK}/items/{codes[5]}")).json()["schedule"]["resource_codes"][0]
    r = await admin.get(f"{BK}/transactions", params={"resource": court_code})
    assert [x["code"] for x in r.json()["rows"]] == [codes[5]]


async def test_transactions_include_tickets_and_resource_filter(admin, staff):
    a, b = await new_court(admin), await new_court(admin)
    hour = await safe_hour()
    ev = (
        await admin.post(
            f"{BK}/sessions",
            json={
                "resource_codes": [a["code"], b["code"]],
                "date": today().isoformat(),
                "start_hour": hour,
                "end_hour": hour + 1,
                "name": "Sự kiện TX",
                "capacity": 3,
                "ticket_price": 30_000,
            },
            headers=idem(),
        )
    ).json()
    t = (
        await staff.post(
            f"{FD}/sessions/{ev['code']}/tickets",
            json={"customer": {"member_code": "HV0115"}},
            headers=idem(),
        )
    ).json()
    r = await admin.get(f"{BK}/transactions", params={"resource": b["code"]})
    rows = r.json()["rows"]
    assert [x["code"] for x in rows] == [t["code"]]
    assert rows[0]["kind"] == "ticket" and rows[0]["resource_codes"] == [a["code"], b["code"]]
    assert rows[0]["amount"] == 30_000


async def test_transactions_date_rules_and_permissions(admin, staff):
    r = await admin.get(
        f"{BK}/transactions",
        params={"from": today().isoformat(), "to": (today() - timedelta(days=1)).isoformat()},
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-016"
    r = await admin.get(
        f"{BK}/transactions",
        params={"from": (today() - timedelta(days=92)).isoformat(), "to": today().isoformat()},
    )
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-020"
    r = await admin.get(
        f"{BK}/transactions",
        params={"from": (today() - timedelta(days=91)).isoformat(), "to": today().isoformat()},
    )
    assert r.status_code == 200
    # NV mặc định xem được Lịch sử giao dịch (người dùng chốt 2026-11-05)
    r = await staff.get(f"{BK}/transactions")
    assert r.status_code == 200, r.text
