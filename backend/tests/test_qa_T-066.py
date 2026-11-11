# ruff: noqa: E501
"""QA T-066 (API, AC1–AC4): Đơn đặt sân hiện số còn phải thu — ``unpaid_amount`` / ``unpaid_blocks`` của ``GET /front-desk/orders``.

Góc nhìn độc lập với ``test_orders_list.py`` của BACKEND: thay vì một kịch bản cố định, chạy chuỗi thao tác ngẫu nhiên (hạt cố định) trên
đơn định kỳ có giảm % — thu tiền mặt một buổi, thu bằng QR một buổi, hủy một buổi (đã thu → hoàn), đánh dấu Không thu được — và sau MỖI bước
đối chiếu với sự thật trong DB: ``unpaid_amount`` = Σ tiền khối Chưa thanh toán, ``unpaid_blocks`` = số khối đó, = số QR cả đơn khi còn khối chưa
thu, = số "Thu cả đơn" tiền mặt thu được; ``total`` = Σ khối chưa hủy; bất biến 0 ≤ unpaid ≤ total. Thêm: đơn nhiều sân khác giá, đơn online
(đã trả trước), phân trang / lọc / tìm không làm lệch số, đơn hủy hết, hai đơn trong cùng một trang không lẫn số của nhau.
"""

import random

from sqlalchemy import select, update

from app.core.db import SessionLocal
from app.modules.booking_engine.models import Booking
from tests.conftest import idem
from tests.helpers_booking import BK, book_order, new_court, random_phone, temp
from tests.helpers_web import checkout, sepay_payload, simulate, webhook
from tests.test_counter_qr import FD, qr, recurring


async def truth(order_code: str) -> list[Booking]:
    async with SessionLocal() as s:
        return list(
            await s.scalars(
                select(Booking).where(Booking.code.like(f"{order_code}-%")).order_by(Booking.code)
            )
        )


async def row(admin, order_code: str, **params) -> dict:
    r = await admin.get(f"{FD}/orders", params={"q": order_code, "size": 50, **params})
    assert r.status_code == 200, r.text
    [found] = [x for x in r.json()["items"] if x["order_code"] == order_code]
    return found


async def check(admin, order_code: str, step: str) -> tuple[int, int]:
    """Đối chiếu một dòng với DB, QR cả đơn. Trả (unpaid_amount, unpaid_blocks)."""
    blocks = await truth(order_code)
    unpaid = [b for b in blocks if b.payment_status == "unpaid"]
    live = [b for b in blocks if b.payment_status != "cancelled"]
    got = await row(admin, order_code)
    want = (sum(b.amount for b in unpaid), len(unpaid))
    assert (got["unpaid_amount"], got["unpaid_blocks"]) == want, (step, got, want)
    assert got["total"] == sum(b.amount for b in live), (step, "total bỏ khối đã hủy")
    assert 0 <= got["unpaid_amount"] <= got["total"], step
    info = (await qr(admin, order_code)).json()
    if unpaid:
        assert (info["status"], info["amount"], info["blocks"]) == ("unpaid", want[0], want[1]), (
            step,
            info,
        )
    else:
        assert info["amount"] == 0 and info["status"] in ("paid", "closed"), (step, info)
    return want


async def cancel_block(admin, order_code: str, code: str):
    return await admin.post(
        f"{FD}/orders/{order_code}/cancel",
        json={"reason": "QA", "codes": [code], "refund_confirmed": True},
        headers=idem(),
    )


async def test_random_operations_keep_unpaid_amount_equal_to_what_collect_takes(admin, anon):
    rng = random.Random(66)
    performed: list[str] = []
    for round_no, pct in enumerate((0, 10, 15)):
        order = await recurring(admin, days_ahead=130 + round_no * 3, pct=pct)
        oc = order["order_code"]
        await check(admin, oc, f"r{round_no} đầu")
        for step in range(8):
            blocks = await truth(oc)
            unpaid = [b for b in blocks if b.payment_status == "unpaid"]
            live = [b for b in blocks if b.payment_status != "cancelled"]
            if not unpaid:
                break
            op = rng.choice(
                ["cash", "qr_item", "cancel_unpaid", "cancel_paid", "uncollectible", "qr_order"]
            )
            target = rng.choice(unpaid)
            tag = f"r{round_no}s{step}:{op}"
            if op == "cash":
                r = await admin.post(
                    f"{BK}/items/{target.code}/collect",
                    json={"method": "cash", "version": target.version},
                    headers=idem(),
                )
                assert r.status_code == 200, (tag, r.text)
            elif op == "qr_item":
                payload = sepay_payload(target.code.replace("-", ""), target.amount)
                assert (await webhook(anon, payload)).status_code == 200
            elif op == "cancel_unpaid":
                if len(live) == 1:
                    continue  # giữ lại ít nhất một khối còn hiệu lực để so tiếp
                assert (await cancel_block(admin, oc, target.code)).status_code == 200, tag
            elif op == "cancel_paid":
                paid = [b for b in blocks if b.payment_status == "paid"]
                if not paid or len(live) == 1:
                    continue
                assert (await cancel_block(admin, oc, rng.choice(paid).code)).status_code == 200, (
                    tag
                )
            elif op == "uncollectible":
                async with (
                    SessionLocal() as s
                ):  # buổi tương lai: đặt thẳng trạng thái (API đòi đã tới giờ)
                    await s.execute(
                        update(Booking)
                        .where(Booking.code == target.code)
                        .values(payment_status="uncollectible", uncollectible_reason="QA")
                    )
                    await s.commit()
            else:  # qr_order: trả đúng số QR cả đơn
                total = (await qr(admin, oc)).json()["amount"]
                assert (
                    await webhook(anon, sepay_payload(oc.replace("-", ""), total))
                ).status_code == 200
            performed.append(op)
            await check(admin, oc, tag)
        # Cuối: nếu còn khối chưa thu thì "Thu cả đơn" tiền mặt thu đúng unpaid_amount
        amount, count = await check(admin, oc, f"r{round_no} cuối")
        if count:
            r = await admin.post(
                f"{BK}/orders/{oc}/collect", json={"method": "cash"}, headers=idem()
            )
            assert r.status_code == 200 and r.json()["amount"] == amount, r.text
            assert len(r.json()["collected"]) == count
            await check(admin, oc, f"r{round_no} sau thu cả đơn")
            assert (await row(admin, oc))["unpaid_amount"] == 0

    assert len(performed) >= 8, performed  # dữ liệu ngẫu nhiên phải thật sự chạy nhiều thao tác
    assert len(set(performed)) >= 5, performed


async def test_two_orders_on_one_page_do_not_mix_amounts_across_filters_and_pages(admin):
    a = await recurring(admin, days_ahead=140, pct=10)
    b = await recurring(admin, days_ahead=143, pct=0)
    ia = sorted(await truth(a["order_code"]), key=lambda x: x.code)
    assert (
        await admin.post(
            f"{BK}/items/{ia[0].code}/collect",
            json={"method": "cash", "version": ia[0].version},
            headers=idem(),
        )
    ).status_code == 200
    want = {
        a["order_code"]: (sum(x.amount for x in ia[1:]), 3),
        b["order_code"]: (b["total"], 4),
    }
    for params in (
        {},
        {"status": "unpaid"},
        {"kind": "recurring"},
        {"size": 1},
        {"size": 1, "page": 2},
    ):
        r = await admin.get(f"{FD}/orders", params={"size": 50, **params})
        assert r.status_code == 200, r.text
        for item in r.json()["items"]:
            assert 0 <= item["unpaid_amount"] <= item["total"] and item["unpaid_blocks"] >= 0
            if item["order_code"] in want:
                assert (item["unpaid_amount"], item["unpaid_blocks"]) == want[item["order_code"]], (
                    params,
                    item["order_code"],
                )
    # Khớp tiền: thu hết đơn a rồi b → 0 / 0, tab Chưa thanh toán không còn hai đơn này
    for o in (a, b):
        assert (
            await admin.post(
                f"{BK}/orders/{o['order_code']}/collect", json={"method": "cash"}, headers=idem()
            )
        ).status_code == 200
        done = await row(admin, o["order_code"])
        assert (done["unpaid_amount"], done["unpaid_blocks"]) == (0, 0)


async def test_multi_court_single_day_order_different_prices_and_online_order(admin, anon):
    c1, c2 = await new_court(admin), await new_court(admin)
    r = await book_order(
        admin,
        [(c1["code"], 18, 19), (c1["code"], 19, 20), (c2["code"], 20, 22)],
        customer=temp("QA Đơn nhiều sân", random_phone()),
    )
    assert r.status_code == 201, r.text
    oc = r.json()["order_code"]
    blocks = await truth(oc)
    assert len(blocks) >= 2
    want_total = sum(b.amount for b in blocks)
    got = await row(admin, oc)
    assert (got["unpaid_amount"], got["unpaid_blocks"], got["total"]) == (
        want_total,
        len(blocks),
        want_total,
    )
    # Thu một khối giá khác → số còn thu giảm đúng bằng tiền khối đó (không phải trung bình)
    first = blocks[-1]
    assert (
        await admin.post(
            f"{BK}/items/{first.code}/collect",
            json={"method": "cash", "version": first.version},
            headers=idem(),
        )
    ).status_code == 200
    got = await row(admin, oc)
    assert (got["unpaid_amount"], got["unpaid_blocks"], got["total"]) == (
        want_total - first.amount,
        len(blocks) - 1,
        want_total,
    )
    # Đơn online đã trả trước: không còn gì để thu
    co = (await checkout(anon, [(c1["code"], 15)])).json()
    assert await simulate(admin, co["pay_ref"], co["amount"]) == "applied"
    online = await row(admin, co["order_code"])
    assert (online["unpaid_amount"], online["unpaid_blocks"]) == (0, 0) and online["total"] == co[
        "amount"
    ]


async def test_fully_cancelled_order_has_nothing_to_collect(admin):
    order = await recurring(admin, days_ahead=146, pct=10)
    oc = order["order_code"]
    preview = (await admin.get(f"{FD}/orders/{oc}/cancel-preview")).json()
    r = await admin.post(
        f"{FD}/orders/{oc}/cancel",
        json={
            "reason": "QA",
            "codes": [i["code"] for i in preview["cancellable"]],
            "refund_confirmed": True,
        },
        headers=idem(),
    )
    assert r.status_code == 200, r.text
    got = await row(admin, oc)
    assert (got["unpaid_amount"], got["unpaid_blocks"], got["total"]) == (0, 0, 0)
    assert got["status"] == "cancelled"
