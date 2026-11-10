# ruff: noqa: E501
"""QA T-061: Lịch sử giao dịch hiện SĐT đầy đủ cho người có quyền ``booking.transactions.view``.

AC1 SĐT đầy đủ (trường ``customer_phone``, không còn ``customer_phone_masked``) · AC2 quyền: Admin và Nhân viên có
quyền xem; Nhân viên bị Admin tắt quyền → 403; khách 403, ẩn danh 401 · AC3 log không chứa SĐT đầy đủ ·
AC4 tìm theo SĐT (kể cả có dấu cách / chấm / một phần) vẫn đúng. Các endpoint khác vẫn che SĐT (hồi quy bằng
các test che SĐT sẵn có của T-005 / T-015 / T-008 / T-019).
"""

import logging
from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.permissions import Perm
from app.modules.auth.models import RolePermission
from app.modules.booking_engine import common
from tests.conftest import idem
from tests.helpers_booking import BK, book, new_court, random_phone, temp

FAR = (datetime.now(settings.tz) + timedelta(days=640)).date()
PERM = Perm.BOOKING_TRANSACTIONS_VIEW.value


def at(day, hour: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, 0, 0, tzinfo=settings.tz)


@pytest.fixture
def clock(monkeypatch):
    state = {"now": at(FAR, 7)}

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return state["now"].astimezone(tz)

    monkeypatch.setattr(common, "datetime", Frozen)

    def set_time(day, hour: int) -> None:
        state["now"] = at(day, hour)

    return set_time


async def pay_cash(client, code):
    return await client.post(
        f"{BK}/items/{code}/collect", json={"method": "cash", "version": 1}, headers=idem()
    )


async def ledger(client, day, **params):
    return await client.get(
        f"{BK}/transactions",
        params={"from": day.isoformat(), "to": day.isoformat(), **params},
    )


async def paid_booking(admin, staff, clock, offset: int, name: str):
    day = FAR + timedelta(days=offset)
    clock(day, 7)
    court = await new_court(admin)
    phone = random_phone()
    r = await book(staff, court["code"], 10, customer=temp(name, phone), day=day)
    assert r.status_code == 201, r.text
    clock(day, 9)
    assert (await pay_cash(admin, r.json()["code"])).status_code == 200
    return day, phone, r.json()


async def test_ac1_ac4_full_phone_and_search_by_phone(admin, staff, clock):
    day, phone, bk = await paid_booking(admin, staff, clock, 1, "QA T061 Đầy Đủ")
    out = (await ledger(admin, day)).json()
    [entry] = out["items"]
    assert entry["customer_phone"] == phone, "SĐT đầy đủ như đã lưu"
    assert "customer_phone_masked" not in entry and "customer_phone_masked" not in str(out)
    assert phone in str(out)
    # AC4: tìm theo SĐT đầy đủ / có dấu cách, chấm / chỉ 4 số cuối vẫn ra đúng một dòng
    for q in (phone, f"{phone[:4]} {phone[4:7]}.{phone[7:]}", phone[-4:], phone[3:8]):
        got = (await ledger(admin, day, q=q)).json()
        assert got["total"] == 1 and got["items"][0]["customer_phone"] == phone, q
    # SĐT khác không khớp
    other = "0" + str((int(phone) + 7) % 10**9).zfill(9)
    assert (await ledger(admin, day, q=other)).json()["total"] == 0
    assert bk["code"] in str(out)


async def test_ac2_staff_with_permission_sees_it_without_permission_gets_403(
    admin, staff, customer, anon, clock
):
    day, phone, _ = await paid_booking(admin, staff, clock, 2, "QA T061 Quyền")
    # Mặc định Nhân viên có quyền xem -> thấy SĐT đầy đủ (người dùng chọn phương án a)
    r = await ledger(staff, day)
    assert r.status_code == 200 and r.json()["items"][0]["customer_phone"] == phone
    assert (await ledger(customer, day)).status_code == 403
    assert (await ledger(anon, day)).status_code == 401
    # Admin tắt quyền của Nhân viên -> 403, không lộ SĐT, có hiệu lực ngay
    async with SessionLocal() as s:
        await s.execute(
            delete(RolePermission).where(
                RolePermission.role == "staff", RolePermission.perm == PERM
            )
        )
        await s.commit()
    try:
        denied = await ledger(staff, day)
        assert denied.status_code == 403 and phone not in denied.text
        assert (await ledger(admin, day)).status_code == 200, "Admin luôn xem được"
    finally:
        async with SessionLocal() as s:
            s.add(RolePermission(role="staff", perm=PERM))
            await s.commit()
    back = await ledger(staff, day)
    assert back.status_code == 200 and back.json()["items"][0]["customer_phone"] == phone


async def test_ac3_logs_never_contain_the_full_phone(admin, staff, clock, caplog):
    caplog.set_level(logging.DEBUG)
    day, phone, bk = await paid_booking(admin, staff, clock, 3, "QA T061 Log")
    for q in (None, phone, f"{phone[:4]} {phone[4:]}", bk["code"]):
        r = await ledger(admin, day, **({"q": q} if q else {}))
        assert r.status_code == 200
    assert (await ledger(staff, day, q=phone)).status_code == 200
    # Bỏ dòng log của chính httpx (client thử ghi URL yêu cầu của test); chỉ xét log của máy chủ
    server = chr(10).join(r.getMessage() for r in caplog.records if not r.name.startswith("httpx"))
    assert phone not in server, "log không chứa SĐT đầy đủ"
    assert phone[1:] not in server


async def test_phone_in_other_responses_stays_masked_for_the_customer_facing_api(
    admin, staff, customer, clock
):
    """Khách / hội viên không thấy SĐT người khác ở bất kỳ đâu: gọi lịch sử → 403 và danh sách khác không rò."""
    day, phone, bk = await paid_booking(admin, staff, clock, 4, "QA T061 Khác")
    for path in ("/booking/transactions", "/booking/search?q=" + phone):
        r = await customer.get(f"{BK.removesuffix('/booking')}{path}")
        assert phone not in r.text, path
