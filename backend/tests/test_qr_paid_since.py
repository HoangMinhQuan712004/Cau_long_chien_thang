"""T-072: collect-qr nhận ``since`` (lúc mở popup) và trả ``qr_paid`` – có tiền QR về cho phạm vi
QR đó từ ``since``. Popup ưu tiên ``qr_paid`` để báo "Đã nhận tiền" đúng cả khi đơn có khối Không
thu được (``status = closed``), và không báo nhận tiền khi máy khác thu tiền mặt / đóng đơn.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.core.db import SessionLocal
from app.modules.booking_engine.models import Booking
from tests.conftest import idem
from tests.helpers_booking import BK
from tests.helpers_web import simulate
from tests.test_counter_qr import FD, recurring
from tests.test_ticket_collect_qr import counter_tickets, today_event


def opened_at() -> str:
    """Mốc lúc mở popup – lùi 2 giây: giờ giao dịch giả lập chỉ tới giây."""
    return (datetime.now(UTC) - timedelta(seconds=2)).isoformat()


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
    async with SessionLocal() as s:  # buổi tương lai: đặt thẳng (API đòi đã tới giờ)
        await s.execute(
            update(Booking)
            .where(Booking.code.in_(codes))
            .values(payment_status="uncollectible", uncollectible_reason="Khách không đến")
        )
        await s.commit()


async def test_order_with_uncollectible_blocks_reports_money(admin):
    """AC1: đơn có khối Không thu được, QR cả đơn phần còn lại, tiền về -> closed + qr_paid."""
    order = await recurring(admin, days_ahead=130)
    code = order["order_code"]
    blocks = sorted(order["bookings"], key=lambda b: b["code"])
    await mark_uncollectible([b["code"] for b in blocks[:2]])
    since = opened_at()
    info = await order_qr(admin, code, since)
    assert (info["status"], info["qr_paid"]) == ("unpaid", False)
    assert info["amount"] == sum(b["payment"]["amount"] for b in blocks[2:])

    assert await simulate(admin, info["pay_ref"], info["amount"]) == "applied"
    after = await order_qr(admin, code, since)
    assert (after["status"], after["qr_paid"]) == ("closed", True)  # FE: qr_paid thắng
    assert (await order_qr(admin, code))["qr_paid"] is False  # không gửi since
    future = (datetime.now(UTC) + timedelta(minutes=5)).isoformat()
    assert (await order_qr(admin, code, future))["qr_paid"] is False  # tiền về trước mốc


async def test_other_desk_closing_the_order_is_not_money(admin):
    """AC2: máy khác thu tiền mặt / Không thu được nốt / chỉ một buổi trả QR -> qr_paid false."""
    cash = await recurring(admin, days_ahead=140)
    since = opened_at()
    r = await admin.post(
        f"{BK}/orders/{cash['order_code']}/collect", json={"method": "cash"}, headers=idem()
    )
    assert r.status_code == 200, r.text
    info = await order_qr(admin, cash["order_code"], since)
    assert (info["status"], info["qr_paid"]) == ("paid", False)  # FE: "xử lý ở máy khác"

    closed = await recurring(admin, days_ahead=150)
    since = opened_at()
    await mark_uncollectible([b["code"] for b in closed["bookings"]])
    info = await order_qr(admin, closed["order_code"], since)
    assert (info["status"], info["qr_paid"]) == ("closed", False)

    # Một buổi trả bằng QR từng buổi, đơn còn buổi chưa thu: popup cả đơn không báo nhận tiền
    partly = await recurring(admin, days_ahead=160)
    since = opened_at()
    one = sorted(partly["bookings"], key=lambda b: b["code"])[0]
    assert await simulate(admin, one["code"].replace("-", ""), one["payment"]["amount"]) == (
        "applied"
    )
    info = await order_qr(admin, partly["order_code"], since)
    assert (info["status"], info["qr_paid"]) == ("unpaid", False)
    assert (await item_qr(admin, one["code"], since))["qr_paid"] is True  # QR buổi đó: có


async def test_block_and_ticket_qr_report_money(admin):
    """AC3: QR từng buổi và QR vé: tiền về -> qr_paid; thu tiền mặt -> paid nhưng qr_paid false."""
    order = await recurring(admin, days_ahead=170)
    first, second = sorted(order["bookings"], key=lambda b: b["code"])[:2]
    since = opened_at()
    assert await simulate(admin, first["code"].replace("-", ""), first["payment"]["amount"]) == (
        "applied"
    )
    info = await item_qr(admin, first["code"], since)
    assert (info["status"], info["qr_paid"]) == ("paid", True)
    r = await admin.post(
        f"{BK}/items/{second['code']}/collect",
        json={"method": "cash", "version": second["version"]},
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    info = await item_qr(admin, second["code"], since)
    assert (info["status"], info["qr_paid"]) == ("paid", False)

    ev = await today_event(admin, 25_000)
    [ticket] = await counter_tickets(admin, ev, 1)
    since = opened_at()
    assert await simulate(admin, ticket["code"].replace("-", ""), 25_000) == "applied"
    info = await item_qr(admin, ticket["code"], since)
    assert (info["status"], info["qr_paid"]) == ("paid", True)


async def test_bad_since_is_e001(admin):
    """AC4: ``since`` sai định dạng / thiếu múi giờ -> 422 E-001 (cả QR đơn lẫn QR buổi)."""
    order = await recurring(admin, days_ahead=180)
    block = order["bookings"][0]["code"]
    for bad in ("hom-nay", "2026-11-12T10:00:00", "2026-11-12T10:00:00 07:00"):
        for url in (
            f"{FD}/orders/{order['order_code']}/collect-qr",
            f"{FD}/items/{block}/collect-qr",
        ):
            r = await admin.get(url, params={"since": bad})
            assert r.status_code == 422 and r.json()["detail"]["code"] == "E-001", (bad, r.text)
