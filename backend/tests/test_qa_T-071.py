# ruff: noqa: E501
"""QA T-071 (API, AC2–AC7): đăng ký vé tại quầy cho nhiều người một lần – ``POST /front-desk/sessions/{mã}/tickets/batch``.

Góc nhìn độc lập với ``test_ticket_batch.py`` của BACKEND: tất cả-hoặc-không-ai khi một dòng ở GIỮA danh sách hỏng, biên 1 / 50 / 51 người,
ghế đang giữ online tính vào chỗ còn, trùng người (hội viên, hồ sơ tạm cùng SĐT khác tên, hội viên + hồ sơ tạm cùng SĐT hội viên), đủ
chỗ chính xác / thiếu 1 chỗ, hai lô đồng thời tranh chỗ cuối, gửi lại cùng khóa 5 lần song song, quyền (Nhân viên có / mất ``booking.ticket.create``),
Origin lạ / thiếu Idempotency-Key, vé mới thu được bằng tiền mặt và QR (T-068), nhãn "Đã có vé" (``member_code`` / ``customer_kind``) và không lộ
trường SĐT thừa, số vé liên tiếp sau lô khi đã có vé lẻ, endpoint một vé không đổi. Đồng hồ engine đóng băng lúc 06:00 (sự kiện 9h–11h hôm nay).
"""

import asyncio
import importlib
from datetime import datetime

import pytest
from sqlalchemy import delete, func, select, text

from app.core.audit import AuditLog
from app.core.config import settings
from app.core.db import SessionLocal
from app.core.permissions import Perm
from app.modules.auth.models import RolePermission
from app.modules.booking_engine import common
from app.modules.booking_engine.models import Ticket
from tests.conftest import idem
from tests.helpers_booking import BK, FD, new_court, random_phone, temp
from tests.qa_tickets import buy, mk_event

t68 = importlib.import_module("tests.test_qa_T-068")
event_today, pay, ref = t68.event_today, t68.pay, t68.ref
PRICE = 50_000


@pytest.fixture
def clock(monkeypatch):
    day = datetime.now(settings.tz).date()
    frozen = datetime(day.year, day.month, day.day, 6, tzinfo=settings.tz)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz)

    monkeypatch.setattr(common, "datetime", Frozen)


async def members(n: int) -> list[str]:
    async with SessionLocal() as s:
        rows = await s.execute(
            text(
                "SELECT member_code FROM customer WHERE kind='member' AND is_active AND member_code IS NOT NULL ORDER BY id LIMIT :n"
            ),
            {"n": n},
        )
        codes = [r[0] for r in rows]
    assert len(codes) >= n, "seed phải có đủ hội viên"
    return codes


def mem(code: str) -> dict:
    return {"member_code": code}


async def batch(client, ev: dict, customers: list, headers: dict | None = None, **body):
    return await client.post(
        f"{FD}/sessions/{ev['code']}/tickets/batch",
        json={"customers": customers, **body},
        headers=headers if headers is not None else idem(),
    )


async def tickets_in_db(ev: dict) -> list[str]:
    async with SessionLocal() as s:
        return list(
            await s.scalars(
                select(Ticket.code)
                .where(Ticket.code.like(f"{ev['code']}-V%"))
                .order_by(Ticket.code)
            )
        )


async def audit_count(ev: dict) -> int:
    async with SessionLocal() as s:
        return await s.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.action == "ticket.create", AuditLog.entity_code.like(f"{ev['code']}-V%")
            )
        )


async def free_seats(admin, ev: dict) -> int:
    d = (await admin.get(f"{BK}/sessions/{ev['code']}")).json()
    return d["capacity"] - len(d["tickets"])


# ---------------------------------------------------------------- AC2, AC5: đăng ký nhiều người


async def test_ac2_ac5_mixed_people_get_consecutive_tickets_in_order_and_existing_holders_pass(
    admin, clock
):
    ev = await event_today(admin, price=PRICE, capacity=12)
    hv = await members(3)
    # Một hội viên đã có vé lẻ trước: vẫn đăng ký được trong lô (chỉ cảnh báo ở FE)
    single = await admin.post(
        f"{FD}/sessions/{ev['code']}/tickets", json={"customer": mem(hv[0])}, headers=idem()
    )
    assert single.status_code == 201, single.text
    phones = [random_phone(), random_phone()]
    people = [
        mem(hv[0]),
        temp("QA Lẻ Một", phones[0]),
        mem(hv[1]),
        temp("QA Lẻ Hai", phones[1], note="đi cùng"),
        mem(hv[2]),
    ]
    r = await batch(admin, ev, people, note="ghi chú chung")
    assert r.status_code == 201, r.text
    out = r.json()["tickets"]
    assert [t["code"] for t in out] == [f"{ev['code']}-V0{i}" for i in range(2, 7)], (
        "số vé liên tiếp sau vé lẻ đã có"
    )
    assert all(
        t["payment"]["payment_status"] == "unpaid" and t["payment"]["amount"] == PRICE for t in out
    )
    assert (await tickets_in_db(ev)) == [f"{ev['code']}-V0{i}" for i in range(1, 7)]
    assert await audit_count(ev) == 6, "mỗi vé một dòng audit"
    # Nhãn "Đã có vé": mã HV cho hội viên, null cho hồ sơ tạm; không có trường SĐT mới
    detail = (await admin.get(f"{BK}/sessions/{ev['code']}")).json()
    by_code = {t["code"]: t for t in detail["tickets"]}
    assert (
        by_code[f"{ev['code']}-V02"]["member_code"] == hv[0]
        and by_code[f"{ev['code']}-V02"]["customer_kind"] == "member"
    )
    assert (
        by_code[f"{ev['code']}-V03"]["member_code"] is None
        and by_code[f"{ev['code']}-V03"]["customer_kind"] == "temp"
    )
    assert {t["member_code"] for t in detail["tickets"] if t["customer_kind"] == "member"} >= set(
        hv
    )
    # Endpoint một vé vẫn chạy và nối tiếp số
    more = await admin.post(
        f"{FD}/sessions/{ev['code']}/tickets",
        json={"customer": temp("QA Vé Lẻ", random_phone())},
        headers=idem(),
    )
    assert more.status_code == 201 and more.json()["code"] == f"{ev['code']}-V07", more.text


# ---------------------------------------------------------------- chỗ: thiếu, đủ, ghế giữ online


async def test_capacity_edges_remaining_and_all_or_nothing(admin, clock):
    ev = await event_today(admin, price=PRICE, capacity=5)
    await batch(admin, ev, [temp(f"QA Sẵn {i}", random_phone()) for i in range(3)])  # còn 2 chỗ
    assert await free_seats(admin, ev) == 2
    three = [temp(f"QA Thừa {i}", random_phone()) for i in range(3)]
    r = await batch(admin, ev, three)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "E-024", r.text
    assert r.json()["detail"]["remaining"] == 2 and "2" in r.json()["detail"]["message"]
    assert len(await tickets_in_db(ev)) == 3, "không tạo vé nào"
    assert await audit_count(ev) == 3
    ok = await batch(admin, ev, three[:2])  # đúng bằng chỗ còn
    assert ok.status_code == 201, ok.text
    full = await batch(admin, ev, three[2:])
    assert (
        full.status_code == 409
        and full.json()["detail"]["code"] == "E-024"
        and full.json()["detail"]["remaining"] == 0
    ), full.text
    assert "đủ chỗ" in full.json()["detail"]["message"]
    single = await admin.post(
        f"{FD}/sessions/{ev['code']}/tickets",
        json={"customer": temp("QA Vé Lẻ", random_phone())},
        headers=idem(),
    )
    assert single.status_code == 409 and single.json()["detail"]["code"] == "E-024", (
        "endpoint một vé giữ hành vi cũ"
    )


async def test_online_held_seats_count_against_the_batch(admin, anon):
    """Không đóng băng giờ: lượt giữ ghế online hết hạn theo now() của DB, giờ giả của engine làm nó hết hạn sớm.
    Sự kiện hôm nay nhưng CHƯA bắt đầu (mua online chỉ khi chưa bắt đầu; vé quầy vẫn đăng ký được)."""
    hour = datetime.now(settings.tz).hour
    if hour > 20:
        pytest.skip("không còn khung chưa bắt đầu trong ngày để mua online")
    court = await new_court(admin)
    r = await admin.post(
        f"{BK}/sessions",
        json={
            "resource_codes": [court["code"]],
            "date": datetime.now(settings.tz).date().isoformat(),
            "start_hour": hour + 2,
            "end_hour": hour + 3,
            "name": "QA sự kiện giữ ghế",
            "capacity": 4,
            "ticket_price": PRICE,
        },
        headers=idem(),
    )
    assert r.status_code == 201, r.text
    ev = r.json()
    hold = await buy(anon, ev["code"], seats=2)
    assert hold.status_code == 201, hold.text  # 2 ghế giữ online chưa trả
    r = await batch(admin, ev, [temp(f"QA {i}", random_phone()) for i in range(3)])
    assert (
        r.status_code == 409
        and r.json()["detail"]["code"] == "E-024"
        and r.json()["detail"]["remaining"] == 2
    ), r.text
    ok = await batch(admin, ev, [temp(f"QA Ok {i}", random_phone()) for i in range(2)])
    assert ok.status_code == 201, ok.text


# ---------------------------------------------------------------- AC4 và lỗi dữ liệu: không vé nào


async def test_ac4_validation_errors_create_nothing(admin, clock):
    ev = await event_today(admin, price=PRICE, capacity=60)
    hv = await members(2)
    phone = random_phone()
    cases = {
        "rỗng": [],
        "trùng hội viên": [mem(hv[0]), temp("QA A", random_phone()), mem(hv[0])],
        "trùng SĐT hồ sơ tạm (khác tên)": [temp("QA B1", phone), temp("QA B2", phone)],
        "thiếu tên": [
            temp("QA Ok", random_phone()),
            {"temp": {"full_name": "", "phone": random_phone()}},
        ],
        "thiếu SĐT": [{"temp": {"full_name": "QA C", "phone": ""}}],
        "SĐT sai": [temp("QA D", "123")],
        "hội viên không có thật ở giữa": [
            temp("QA E1", random_phone()),
            mem("HV9999999"),
            temp("QA E2", random_phone()),
        ],
        "quá 50 người": [temp(f"QA N{i}", random_phone()) for i in range(51)],
        "không phải danh sách": "abc",
        "phần tử rỗng": [{}],
    }
    for name, customers in cases.items():
        r = await batch(admin, ev, customers)
        assert r.status_code in (404, 409, 422), (name, r.status_code, r.text[:160])
        assert r.status_code != 500, name
        if name != "hội viên không có thật ở giữa":
            assert r.status_code == 422, (name, r.text[:160])
    assert await tickets_in_db(ev) == [], (
        "mọi lô lỗi đều không tạo vé nào (kể cả lỗi ở GIỮA danh sách)"
    )
    assert await audit_count(ev) == 0
    # Hồ sơ tạm cùng SĐT với hội viên: báo trùng/không cho mạo danh, không tạo gì
    async with SessionLocal() as s:
        hv_phone = await s.scalar(
            text("SELECT phone FROM customer WHERE member_code=:c"), {"c": hv[0]}
        )
    r = await batch(admin, ev, [temp("QA Giả Hội Viên", hv_phone)])
    assert r.status_code in (409, 422) and await tickets_in_db(ev) == [], r.text[:160]
    # Biên: 1 người và 50 người đều được (sự kiện có 60 chỗ)
    assert (await batch(admin, ev, [temp("QA Một", random_phone())])).status_code == 201
    r = await batch(admin, ev, [temp(f"QA Năm Mươi {i}", random_phone()) for i in range(50)])
    assert r.status_code == 201 and len(r.json()["tickets"]) == 50, r.text[:160]
    assert len(await tickets_in_db(ev)) == 51
    # Ghi chú chung: 201 ký tự bị từ chối, đúng 200 ký tự được
    assert (
        await batch(admin, ev, [temp("QA Ghi Chú", random_phone())], note="x" * 201)
    ).status_code == 422
    assert (
        await batch(admin, ev, [temp("QA Ghi Chú 2", random_phone())], note="x" * 200)
    ).status_code == 201


# ---------------------------------------------------------------- AC6: đồng thời, gửi lại


async def test_ac6_two_batches_racing_for_the_last_seats_and_replay(admin, staff, clock):
    ev = await event_today(admin, price=PRICE, capacity=4)
    a = [temp(f"QA Máy A{i}", random_phone()) for i in range(3)]
    b = [temp(f"QA Máy B{i}", random_phone()) for i in range(3)]
    ra, rb = await asyncio.gather(batch(admin, ev, a), batch(staff, ev, b))
    assert sorted((ra.status_code, rb.status_code)) == [201, 409], (ra.text, rb.text)
    loser = ra if ra.status_code == 409 else rb
    assert loser.json()["detail"]["code"] == "E-024" and loser.json()["detail"]["remaining"] == 1
    assert len(await tickets_in_db(ev)) == 3 and await free_seats(admin, ev) == 1
    # Gửi lại cùng khóa 5 lần song song → một lần tạo
    ev2 = await event_today(admin, price=PRICE, capacity=10)
    key = idem()
    people = [temp(f"QA Lặp {i}", random_phone()) for i in range(3)]
    rs = await asyncio.gather(*[batch(admin, ev2, people, headers=key) for _ in range(5)])
    ok = [r for r in rs if r.status_code == 201]
    assert ok and all(r.status_code in (201, 409) for r in rs), [r.text[:80] for r in rs]
    assert len(await tickets_in_db(ev2)) == 3, "chỉ tạo một lần"
    again = await batch(admin, ev2, people, headers=key)
    assert again.status_code == 201 and again.json() == ok[0].json(), "phát lại cùng kết quả"
    assert len(await tickets_in_db(ev2)) == 3
    # Cùng khóa nhưng nội dung khác: không tạo thêm
    other = await batch(admin, ev2, [temp("QA Khác", random_phone())], headers=key)
    assert other.status_code in (409, 422) and len(await tickets_in_db(ev2)) == 3


# ---------------------------------------------------------------- quyền, Origin, khóa


async def test_permissions_origin_and_idempotency_key(admin, staff, customer, anon, clock):
    ev = await event_today(admin, price=PRICE, capacity=10)
    one = [temp("QA Quyền", random_phone())]
    assert (await batch(anon, ev, one)).status_code == 401
    assert (await batch(customer, ev, one)).status_code == 403
    assert (await batch(staff, ev, one)).status_code == 201, (
        "Nhân viên mặc định có booking.ticket.create"
    )
    miss = await admin.post(
        f"{FD}/sessions/{ev['code']}/tickets/batch",
        json={"customers": [temp("QA Thiếu Khóa", random_phone())]},
    )
    assert miss.status_code in (400, 422), miss.text[:120]
    evil = await batch(
        admin,
        ev,
        [temp("QA Origin", random_phone())],
        headers={**idem(), "Origin": "https://evil.example"},
    )
    assert evil.status_code == 403, evil.text[:120]
    before = len(await tickets_in_db(ev))
    perm = Perm.BOOKING_TICKET_CREATE.value
    async with SessionLocal() as s:
        await s.execute(
            delete(RolePermission).where(
                RolePermission.role == "staff", RolePermission.perm == perm
            )
        )
        await s.commit()
    try:
        assert (await batch(staff, ev, [temp("QA Mất Quyền", random_phone())])).status_code == 403
    finally:
        async with SessionLocal() as s:
            s.add(RolePermission(role="staff", perm=perm))
            await s.commit()
    assert len(await tickets_in_db(ev)) == before, "bị từ chối thì không tạo vé"


# ---------------------------------------------------------------- AC7: thu tiền vé mới, E-004


async def test_ac7_new_tickets_can_be_paid_by_cash_and_qr_and_event_state_rules(admin, anon, clock):
    ev = await event_today(admin, price=PRICE, capacity=10)
    r = await batch(
        admin, ev, [temp("QA Thu Một", random_phone()), temp("QA Thu Hai", random_phone())]
    )
    assert r.status_code == 201, r.text
    t1, t2 = (t["code"] for t in r.json()["tickets"])
    cash = await admin.post(
        f"{BK}/items/{t1}/collect", json={"method": "cash", "version": 1}, headers=idem()
    )
    assert cash.status_code == 200, cash.text
    qr = await admin.get(f"{FD}/items/{t2}/collect-qr")
    assert (
        qr.status_code == 200 and qr.json()["amount"] == PRICE and qr.json()["pay_ref"] == ref(t2)
    )
    assert (await pay(anon, PRICE, ref(t2), ref(ev["code"])))[0] == "applied"
    # Sự kiện ngày mai: vé quầy chỉ cho hôm nay → E-004 (như một vé), không tạo gì
    tomorrow_ev = await mk_event(admin, price=PRICE)
    r = await batch(admin, tomorrow_ev, [temp("QA Ngày Mai", random_phone())])
    assert r.status_code == 422 and r.json()["detail"]["code"] == "E-004", r.text
    assert await tickets_in_db(tomorrow_ev) == []
    # Sự kiện không tồn tại → 404 (không 5xx)
    r = await admin.post(
        f"{FD}/sessions/BK-20000101-999/tickets/batch",
        json={"customers": [temp("QA Lạ", random_phone())]},
        headers=idem(),
    )
    assert r.status_code == 404, r.text
