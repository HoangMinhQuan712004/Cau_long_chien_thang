"""T-071: đăng ký vé tại quầy cho nhiều người một lần – tất cả hoặc không ai, thiếu chỗ báo "Chỉ còn
n chỗ." (``remaining``), trùng người -> E-001, đồng thời không vượt sức chứa, gửi lại cùng key không
tạo thêm; danh sách vé có ``member_code`` để FE hiện "Đã có vé" (không thêm SĐT).
"""

import asyncio

from sqlalchemy import func, select

from app.core.audit import AuditLog
from app.core.db import SessionLocal
from app.modules.booking_engine.models import Ticket
from tests.conftest import idem
from tests.helpers_booking import BK, FD, member, random_phone, safe_hour, temp, today
from tests.test_ticket_online import new_event


async def today_event(admin, capacity: int = 8, price: int = 40_000) -> dict:
    hour = await safe_hour()
    return await new_event(
        admin, day=today(), hours=(hour, hour + 1), capacity=capacity, price=price
    )


async def batch(client, ev: dict, customers: list[dict], headers: dict | None = None, **body):
    return await client.post(
        f"{FD}/sessions/{ev['code']}/tickets/batch",
        json={"customers": customers, **body},
        headers=headers or idem(),
    )


async def ticket_count(ev: dict) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count()).select_from(Ticket).where(Ticket.code.like(f"{ev['code']}-V%"))
        )


async def test_four_people_mixed_get_consecutive_tickets(admin):
    """AC2, AC5: 2 hội viên + 2 hồ sơ tạm -> 4 vé liên tiếp theo thứ tự; danh sách vé có mã HV."""
    ev = await today_event(admin, price=45_000)
    phones = [random_phone(), random_phone()]
    customers = [
        member("HV0012"),
        temp("Khách Lẻ Một", phones[0]),
        member("HV0031"),
        temp("Khách Lẻ Hai", phones[1], note="Đi cùng HV0031"),
    ]
    r = await batch(admin, ev, customers)
    assert r.status_code == 201, r.text
    tickets = r.json()["tickets"]
    assert [t["code"] for t in tickets] == [f"{ev['code']}-V{n:02d}" for n in (1, 2, 3, 4)]
    assert [t["customer"]["name"] for t in tickets] == [
        "Trần Minh Đức",
        "Khách Lẻ Một",
        "Phạm Văn Nam",
        "Khách Lẻ Hai",
    ]
    assert {(t["payment"]["payment_status"], t["payment"]["amount"]) for t in tickets} == {
        ("unpaid", 45_000)
    }
    assert tickets[3]["note"] == "Đi cùng HV0031"

    detail = (await admin.get(f"{BK}/sessions/{ev['code']}")).json()
    assert detail["taken"] == 4
    by_code = {t["code"]: t for t in detail["tickets"]}
    assert [by_code[t["code"]]["member_code"] for t in tickets] == ["HV0012", None, "HV0031", None]
    assert [by_code[t["code"]]["customer_kind"] for t in tickets] == [
        "member",
        "temp",
        "member",
        "temp",
    ]
    async with SessionLocal() as s:
        n = await s.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "ticket.create",
                AuditLog.entity_code.in_([t["code"] for t in tickets]),
            )
        )
    assert n == 4  # mỗi vé một dòng nhật ký

    # Người đã có vé vẫn đăng ký thêm được (chỉ cảnh báo ở FE); vé mới thu tiền như vé thường
    r = await batch(admin, ev, [member("HV0012")])
    assert r.status_code == 201, r.text
    [extra] = r.json()["tickets"]
    paid = await admin.post(
        f"{BK}/items/{extra['code']}/collect",
        json={"method": "cash", "version": extra["version"]},
        headers=idem(),
    )
    assert paid.status_code == 200 and paid.json()["payment"]["payment_status"] == "paid"


async def test_not_enough_seats_creates_nothing(admin):
    """AC3: thiếu chỗ -> 409 E-024 "Chỉ còn n chỗ." + ``remaining``, không vé nào; đầy -> đủ chỗ."""
    ev = await today_event(admin, capacity=3)
    assert (await batch(admin, ev, [member("HV0045")])).status_code == 201
    r = await batch(admin, ev, [member("HV0058"), member("HV0087"), temp("Khách Ba")])
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": "E-024", "message": "Chỉ còn 2 chỗ.", "remaining": 2}
    assert await ticket_count(ev) == 1
    assert (await batch(admin, ev, [member("HV0058"), member("HV0087")])).status_code == 201
    r = await batch(admin, ev, [temp("Khách Muộn")])
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": "E-024", "message": "Sự kiện đã đủ chỗ.", "remaining": 0}
    assert await ticket_count(ev) == 3


async def test_validation_duplicates_empty_and_limits(admin):
    """AC4 + E-001: trùng hội viên / trùng SĐT hồ sơ tạm, rỗng, quá 50, thiếu tên -> 422."""
    ev = await today_event(admin)
    phone = random_phone()
    cases = [
        [member("HV0012"), temp("Ai Đó"), member("HV0012")],
        [temp("Khách A", phone), temp("Khách A lần hai", phone)],
        [],
        [temp(f"Khách {i}") for i in range(51)],
        [{"temp": {"full_name": "", "phone": random_phone()}}],
    ]
    for customers in cases:
        r = await batch(admin, ev, customers)
        assert r.status_code == 422, (len(customers), r.text)
        assert r.json()["detail"]["code"] == "E-001", r.text
    r = await batch(admin, ev, [member("HV0012"), member("HV0012")])
    assert "Trần Minh Đức" in r.json()["detail"]["message"]
    assert await ticket_count(ev) == 0  # hồ sơ tạm đã tạo dở cũng không để lại vé nào


async def test_concurrent_batches_never_exceed_capacity_and_replay(admin, staff):
    """AC6: hai máy cùng lúc sát số chỗ -> một bên được, một bên E-024; cùng key -> không thêm."""
    ev = await today_event(admin, capacity=4)
    first = [temp("Nhóm A1"), temp("Nhóm A2"), temp("Nhóm A3")]
    second = [temp("Nhóm B1"), temp("Nhóm B2"), temp("Nhóm B3")]
    a, b = await asyncio.gather(batch(admin, ev, first), batch(staff, ev, second))
    assert sorted((a.status_code, b.status_code)) == [201, 409], (a.text, b.text)
    loser = a if a.status_code == 409 else b
    assert loser.json()["detail"]["remaining"] == 1
    assert await ticket_count(ev) == 3

    key, last = idem(), [temp("Khách Cuối")]  # cùng key + cùng body (temp() có SĐT ngẫu nhiên)
    r1 = await batch(admin, ev, last, headers=key)
    r2 = await batch(admin, ev, last, headers=key)
    assert r1.status_code == r2.status_code == 201 and r1.json() == r2.json()
    assert r2.headers.get("idempotent-replayed") == "true"
    assert await ticket_count(ev) == 4


async def test_wrong_day_permission_and_single_endpoint_unchanged(admin, customer):
    """E-004 như một vé; khách 403; endpoint một vé vẫn chạy như cũ."""
    future = await new_event(admin)  # ngày mai
    r = await batch(admin, future, [temp("Khách Sớm")])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-004"
    ev = await today_event(admin)
    assert (await batch(customer, ev, [temp("Khách")])).status_code == 403
    r = await admin.post(
        f"{FD}/sessions/{ev['code']}/tickets", json={"customer": member("HV0012")}, headers=idem()
    )
    assert r.status_code == 201 and r.json()["code"] == f"{ev['code']}-V01"
