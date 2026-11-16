# ruff: noqa: E501
"""QA T-072 (API): ``collect-qr?since=`` → ``qr_paid`` – popup biết tiền QR vừa về (kể cả khi đơn có khối Không thu được).

Góc nhìn độc lập với ``test_qr_paid_since.py`` của BACKEND: kịch bản gốc T-65-1 (khối cuối trả QR trong đơn đã có Không thu được),
QR cả đơn chỉ ``true`` khi hết khối chưa thu, QR buổi lẻ chỉ ``true`` cho đúng buổi đó, tiền mặt (máy khác) → ``paid`` + ``false``, tiền
cần hoàn (lệch số) không làm ``true``, tiền của đơn khác không rò, mốc ``since`` (quá khứ xa / tương lai / đúng sau lúc tiền về),
định dạng ``since`` (thiếu múi giờ, dấu + chưa mã hóa, chữ), cả ba loại: đơn, buổi, vé; quyền không đổi.
"""

import importlib
from datetime import UTC, datetime, timedelta, timezone

import pytest
from sqlalchemy import update

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.booking_engine import common
from app.modules.booking_engine.models import Booking
from tests.conftest import idem
from tests.helpers_booking import BK
from tests.test_counter_qr import FD, qr

t65 = importlib.import_module("tests.test_qa_T-065")
t68 = importlib.import_module("tests.test_qa_T-068")
pay, ref, sorted_blocks = t65.pay, t65.ref, t65.sorted_blocks
cash, counter_tickets, event_today = t68.cash, t68.counter_tickets, t68.event_today
VN = timezone(timedelta(hours=7))


@pytest.fixture
def clock(monkeypatch):
    """Đóng băng đồng hồ engine lúc 06:00 hôm nay: vé quầy chỉ đăng ký cho sự kiện hôm nay (9h–11h luôn ở tương lai)."""
    day = datetime.now(settings.tz).date()
    frozen = datetime(day.year, day.month, day.day, 6, tzinfo=settings.tz)

    class Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return frozen.astimezone(tz)

    monkeypatch.setattr(common, "datetime", Frozen)


def since_now(seconds: int = 2) -> str:
    return (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()


async def order_qr(client, code: str, since: str | None = None) -> dict:
    params = {"since": since} if since else {}
    r = await client.get(f"{FD}/orders/{code}/collect-qr", params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def item_qr(client, code: str, since: str | None = None) -> dict:
    params = {"since": since} if since else {}
    r = await client.get(f"{FD}/items/{code}/collect-qr", params=params)
    assert r.status_code == 200, r.text
    return r.json()


async def mark_uncollectible(codes: list[str]) -> None:
    async with SessionLocal() as s:
        await s.execute(
            update(Booking)
            .where(Booking.code.in_(codes))
            .values(payment_status="uncollectible", uncollectible_reason="QA")
        )
        await s.commit()


# ---------------------------------------------------------------- kịch bản gốc T-65-1


async def test_t65_1_last_block_paid_by_qr_in_an_order_with_uncollectible_blocks(admin, anon):
    order, rows = await sorted_blocks(admin, 150)
    oc = order["order_code"]
    await mark_uncollectible([rows[0].code, rows[1].code])
    since = since_now()
    info = await order_qr(admin, oc, since)
    assert (info["status"], info["qr_paid"], info["blocks"]) == ("unpaid", False, 2)
    # Tiền về cho phần còn lại (QR cả đơn): khi đã hết khối chưa thu → closed nhưng qr_paid = true
    outcome, _ = await pay(anon, info["amount"], ref(oc), ref(oc))
    assert outcome == "applied"
    after = await order_qr(admin, oc, since)
    assert (after["status"], after["amount"], after["qr_paid"]) == ("closed", 0, True)
    # Không gửi since → luôn false (hành vi cũ); since sau lúc tiền về → false
    assert (await order_qr(admin, oc))["qr_paid"] is False
    future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    assert (await order_qr(admin, oc, future))["qr_paid"] is False


async def test_per_block_qr_pays_only_that_block_and_whole_order_stays_false_until_none_left(
    admin, anon
):
    order, rows = await sorted_blocks(admin, 152)
    oc = order["order_code"]
    since = since_now()
    a, b = rows[0], rows[1]
    assert (await pay(anon, a.amount, ref(a.code), ref(oc)))[0] == "applied"
    assert (await item_qr(admin, a.code, since))["qr_paid"] is True
    assert (await item_qr(admin, b.code, since))["qr_paid"] is False, "khối khác chưa có tiền"
    whole = await order_qr(admin, oc, since)
    assert (whole["status"], whole["qr_paid"]) == ("unpaid", False), (
        "còn khối chưa thu → cả đơn chưa báo"
    )
    # Thu nốt các khối còn lại bằng QR cả đơn: giờ hết khối chưa thu → true
    assert (await pay(anon, whole["amount"], ref(oc), ref(oc)))[0] == "applied"
    done = await order_qr(admin, oc, since)
    assert (done["status"], done["qr_paid"]) == ("paid", True)


# ---------------------------------------------------------------- không báo nhầm


async def test_cash_by_another_desk_is_paid_but_not_qr_paid(admin):
    order, rows = await sorted_blocks(admin, 154)
    oc = order["order_code"]
    since = since_now()
    r = await admin.post(f"{BK}/orders/{oc}/collect", json={"method": "cash"}, headers=idem())
    assert r.status_code == 200, r.text
    info = await order_qr(admin, oc, since)
    assert (info["status"], info["amount"], info["qr_paid"]) == ("paid", 0, False)
    assert (await item_qr(admin, rows[0].code, since))["qr_paid"] is False


async def test_refund_needed_money_and_other_orders_never_set_qr_paid(admin, anon):
    order, rows = await sorted_blocks(admin, 156)
    other, other_rows = await sorted_blocks(admin, 158)
    oc, oc2 = order["order_code"], other["order_code"]
    since = since_now()
    a = rows[0]
    # Lệch số (±1, gấp đôi) → cần hoàn → không phải tiền đã áp
    for amount in (a.amount - 1, a.amount + 1, a.amount * 2):
        assert (await pay(anon, amount, ref(a.code), ref(oc)))[0] == "refund_needed"
    assert (await item_qr(admin, a.code, since))["qr_paid"] is False
    assert (await order_qr(admin, oc, since))["qr_paid"] is False
    # Đơn khác trả QR đủ → không rò sang đơn này
    full = await order_qr(admin, oc2, since)
    assert (await pay(anon, full["amount"], ref(oc2), ref(oc2)))[0] == "applied"
    assert (await order_qr(admin, oc2, since))["qr_paid"] is True
    assert (await order_qr(admin, oc, since))["qr_paid"] is False
    assert (await item_qr(admin, a.code, since))["qr_paid"] is False
    assert (await item_qr(admin, other_rows[0].code, since))["qr_paid"] is True


# ---------------------------------------------------------------- vé


async def test_ticket_qr_paid_true_for_qr_false_for_cash(admin, anon, clock):
    ev = await event_today(admin)
    codes = await counter_tickets(admin, ev, 2)
    since = since_now()
    assert (await item_qr(admin, codes[0], since))["qr_paid"] is False
    assert (await pay(anon, 50_000, ref(codes[0]), ref(ev["code"])))[0] == "applied"
    assert (await item_qr(admin, codes[0], since))["qr_paid"] is True
    assert (await cash(admin, codes[1])).status_code == 200
    info = await item_qr(admin, codes[1], since)
    assert (info["status"], info["qr_paid"]) == ("paid", False), "thu tiền mặt không phải QR"


# ---------------------------------------------------------------- mốc since và định dạng


async def test_since_boundaries_and_formats(admin, anon):
    order, rows = await sorted_blocks(admin, 160)
    oc, a = order["order_code"], rows[0]
    assert (await pay(anon, a.amount, ref(a.code), ref(oc)))[0] == "applied"
    # Quá khứ xa → true; hiện tại / tương lai → false; cùng một mốc dạng +07:00 và Z cho cùng kết quả
    long_ago = (datetime.now(UTC) - timedelta(days=3)).isoformat()
    assert (await item_qr(admin, a.code, long_ago))["qr_paid"] is True
    vn = (datetime.now(UTC) - timedelta(days=3)).astimezone(VN).isoformat()
    r = await admin.get(
        f"{FD}/items/{a.code}/collect-qr", params={"since": vn}
    )  # httpx mã hóa dấu +
    assert r.status_code == 200 and r.json()["qr_paid"] is True, r.text
    z = (datetime.now(UTC) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert (await item_qr(admin, a.code, z))["qr_paid"] is True
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    assert (await item_qr(admin, a.code, future))["qr_paid"] is False
    # Định dạng sai → 422 E-001 ở cả hai endpoint: thiếu múi giờ, chữ, ngày không có thật, dấu + chưa mã hóa
    for bad in ("2026-11-12T10:00:00", "hôm qua", "2026-13-40T10:00:00Z", "1731000000", ""):
        for path in (f"{FD}/orders/{oc}/collect-qr", f"{FD}/items/{a.code}/collect-qr"):
            r = await admin.get(path, params={"since": bad})
            if bad == "":
                assert r.status_code in (200, 422), (
                    bad,
                    r.status_code,
                )  # rỗng: coi như không gửi hoặc từ chối, không 5xx
            else:
                assert r.status_code == 422 and r.json()["detail"]["code"] == "E-001", (
                    bad,
                    path,
                    r.status_code,
                    r.text[:120],
                )
    raw = await admin.get(
        f"{FD}/items/{a.code}/collect-qr?since=2026-11-12T10:00:00+07:00"
    )  # '+' thành khoảng trắng
    assert raw.status_code == 422 and raw.json()["detail"]["code"] == "E-001", raw.text[:120]


async def test_permissions_unchanged_and_other_fields_unchanged(admin, staff, customer, anon):
    order, rows = await sorted_blocks(admin, 162)
    oc = order["order_code"]
    since = since_now()
    base = await qr(admin, oc)
    assert base.status_code == 200
    for who, expect in ((staff, 200), (customer, 403), (anon, 401)):
        r = await who.get(f"{FD}/orders/{oc}/collect-qr", params={"since": since})
        assert r.status_code == expect, who
        r = await who.get(f"{FD}/items/{rows[0].code}/collect-qr", params={"since": since})
        assert r.status_code == expect, who
    with_since = await order_qr(admin, oc, since)
    plain = base.json()
    assert {k: v for k, v in with_since.items() if k != "qr_paid"} == {
        k: v for k, v in plain.items() if k != "qr_paid"
    }
