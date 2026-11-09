# ruff: noqa: E501, F401, F811
"""QA T-057 AC8: backfill sổ tiền vào trên dữ liệu ngẫu nhiên – kiểm bằng oracle Python độc lập với migration ``e3a17c9b5d24``.

Sinh ngẫu nhiên (hạt cố định) đơn quầy / online, booking đủ trạng thái (chưa thu, đã thu, đã hủy có hoàn, Không thu được, 0 đ),
vé nhiều khách. Sau khi nâng: Σ sổ = Σ tiền đã thu − Σ đã hoàn; mỗi mục tiền đúng một lần; không dòng nào trộn lần thu khác;
số dòng = số khóa gộp (đơn / sự kiện, giờ thu, phương thức, người thu [, khách vé]); giờ đúng; down / up / check sạch.
"""

import random

from alembic import command

from tests.test_payment_ledger_migration import (  # noqa: F401  (fixture mig_db)
    BEFORE,
    TARGET,
    alembic,
    booking,
    fetch,
    insert,
    mig_db,
    order,
    ticket,
    write,
)

T = [f"'2026-10-{d:02d} {h:02d}:00+07'" for d in (20, 21, 22, 23) for h in (9, 15)]
CANCEL_T = [f"'2026-10-{d:02d} 18:30+07'" for d in (25, 26, 27)]
COLLECTORS = [
    ("'staff'", "7", "'NV001'"),
    ("'staff'", "8", "'NV002'"),
    ("'admin'", "1", "'Admin'"),
]
METHODS = ["'cash'", "'transfer'"]
AMOUNTS = [0, 40_000, 50_000, 70_000, 100_000]


def money_columns(
    rng: random.Random, status: str, amount: int, online_pay: str | None, k: int
) -> dict:
    """Cột thanh toán của một dòng + mô tả cho oracle."""
    cols: dict[str, str] = {}
    meta: dict = {"status": status, "amount": amount}
    if status in ("paid", "cancelled"):
        t = rng.choice(T)
        if online_pay:
            who = ("'web'", "NULL", "'Khách đặt online'")
            method = "'online_transfer'"
            cols["gateway_ref"] = f"'sepay:{online_pay}{t[9:11]}{t[12:14]}:{k}'"
        else:
            who = rng.choice(COLLECTORS)
            method = rng.choice(METHODS)
        cols |= {
            "payment_status": "'paid'",
            "payment_method": method,
            "paid_at": t,
            "collected_by_type": who[0],
            "collected_by_id": who[1],
            "collected_by_label": who[2],
        }
        meta |= {"paid_at": t, "method": method, "who": who}
        if status == "cancelled":
            c = rng.choice(CANCEL_T)
            refund = amount if rng.random() < 0.7 else 0
            cols |= {
                "payment_status": "'cancelled'",
                "cancel_reason": "'QA'",
                "cancelled_at": c,
                "cancelled_by_type": "'admin'",
                "cancelled_by_id": "1",
                "cancelled_by_label": "'Admin'",
                "refund_amount": str(refund),
            }
            meta |= {"cancelled_at": c, "refund": refund}
    elif status == "uncollectible":
        cols |= {"payment_status": "'uncollectible'", "uncollectible_reason": "'Khách bỏ về'"}
    return cols | {"_meta": meta}  # type: ignore[dict-item]


async def test_random_backfill_matches_an_independent_oracle(mig_db):
    rng = random.Random(57)
    statements = [
        insert(
            "session",
            id="1",
            tenant_id="1",
            code="'BK-20261101-900'",
            name="'Giao lưu'",
            play_date="'2026-11-01'",
            start_at="'2026-11-01 19:00+07'",
            end_at="'2026-11-01 21:00+07'",
            capacity="50",
            ticket_price="30000",
            created_by_type="'admin'",
            created_by_label="'Admin'",
        )
    ]
    bookings: list[dict] = []
    tickets: list[dict] = []
    bid = 0
    for oid in range(1, 9):
        online = oid % 3 == 0
        statements.append(
            order(oid, f"BK-20261101-{oid:03d}", "'online'" if online else "'counter'")
        )
        for seq in range(1, rng.randint(2, 6)):
            bid += 1
            status = rng.choice(["unpaid", "paid", "paid", "paid", "cancelled", "uncollectible"])
            if online and status == "uncollectible":
                status = "unpaid"
            amount = rng.choice(AMOUNTS)
            cols = money_columns(rng, status, amount, f"{oid}" if online else None, seq)
            meta = cols.pop("_meta")
            if status == "uncollectible":
                cols |= {
                    "marked_by_type": "'admin'",
                    "marked_by_label": "'Admin'",
                    "marked_at": "now()",
                }
            statements.append(booking(bid, oid, seq, amount, **cols))
            bookings.append({"id": bid, "order": oid, **meta})
    for tid in range(1, 25):
        status = rng.choice(["unpaid", "paid", "paid", "cancelled"])
        who_ref = rng.choice(["a", "b", "c"])
        amount = 30_000
        cols = money_columns(rng, status, amount, None, tid)
        meta = cols.pop("_meta")
        cols.pop("gateway_ref", None)
        statements.append(ticket(tid, tid, amount, who_ref, **cols))
        tickets.append({"id": tid, "ref": who_ref, **meta})
    await write(*statements)
    await alembic(command.upgrade, TARGET)

    def counted(rows):
        return [r for r in rows if r["status"] in ("paid", "cancelled") and r["amount"] > 0]

    # Dữ liệu sinh ra phải đủ đa dạng để oracle có nghĩa
    assert len(counted(bookings)) >= 8 and len(counted(tickets)) >= 5
    assert any(r.get("refund", 0) > 0 for r in bookings) and any(
        r.get("refund", 0) > 0 for r in tickets
    )
    assert any(r["status"] == "unpaid" for r in bookings) and any(
        r["status"] == "uncollectible" for r in bookings
    )
    assert any(r["amount"] == 0 and r["status"] == "paid" for r in bookings)
    assert {r["method"] for r in counted(bookings)} >= {"'cash'", "'transfer'", "'online_transfer'"}

    paid_total = sum(r["amount"] for r in counted(bookings + tickets))
    refund_total = sum(r.get("refund", 0) for r in bookings + tickets)

    # P1: tổng sổ
    [(inn, ref)] = await fetch(
        "SELECT coalesce(sum(amount) FILTER (WHERE kind='in'), 0), coalesce(sum(amount) FILTER (WHERE kind='refund'), 0) FROM booking.payment_entry"
    )
    assert (inn, ref) == (paid_total, refund_total), "Σ in = Σ đã thu, Σ refund = Σ đã hoàn"

    # P2: mỗi mục tiền xuất hiện đúng một lần ở dòng `in` (và dòng `refund` nếu có hoàn) đúng số tiền
    in_b = {
        r[0]: r[1:]
        for r in await fetch(
            "SELECT i.booking_id, i.amount, e.id FROM booking.payment_entry_item i JOIN booking.payment_entry e ON e.id=i.entry_id WHERE e.kind='in' AND i.booking_id IS NOT NULL"
        )
    }
    in_t = {
        r[0]: r[1:]
        for r in await fetch(
            "SELECT i.ticket_id, i.amount, e.id FROM booking.payment_entry_item i JOIN booking.payment_entry e ON e.id=i.entry_id WHERE e.kind='in' AND i.ticket_id IS NOT NULL"
        )
    }
    rf_b = {
        r[0]: r[1:]
        for r in await fetch(
            "SELECT i.booking_id, i.amount, e.id FROM booking.payment_entry_item i JOIN booking.payment_entry e ON e.id=i.entry_id WHERE e.kind='refund' AND i.booking_id IS NOT NULL"
        )
    }
    rf_t = {
        r[0]: r[1:]
        for r in await fetch(
            "SELECT i.ticket_id, i.amount, e.id FROM booking.payment_entry_item i JOIN booking.payment_entry e ON e.id=i.entry_id WHERE e.kind='refund' AND i.ticket_id IS NOT NULL"
        )
    }
    for rows, got_in, got_rf in ((bookings, in_b, rf_b), (tickets, in_t, rf_t)):
        assert set(got_in) == {r["id"] for r in counted(rows)}, "chỉ khoản đã thu, tiền > 0"
        assert all(got_in[r["id"]][0] == r["amount"] for r in counted(rows))
        refunded = [r for r in rows if r.get("refund", 0) > 0]
        assert set(got_rf) == {r["id"] for r in refunded}
        assert all(got_rf[r["id"]][0] == r["refund"] for r in refunded)
    assert (await fetch("SELECT count(*) FROM booking.payment_entry_item"))[0][0] == len(
        in_b
    ) + len(in_t) + len(rf_b) + len(rf_t)

    # P3: dòng = Σ mục; P5: không trộn giờ thu / phương thức trong một dòng
    bad = await fetch(
        "SELECT e.id FROM booking.payment_entry e JOIN booking.payment_entry_item i ON i.entry_id=e.id GROUP BY e.id, e.amount HAVING sum(i.amount) <> e.amount"
    )
    assert bad == []
    mixed = await fetch(
        "SELECT e.id FROM booking.payment_entry e JOIN booking.payment_entry_item i ON i.entry_id=e.id "
        "LEFT JOIN booking.booking b ON b.id=i.booking_id LEFT JOIN booking.ticket t ON t.id=i.ticket_id "
        "WHERE e.kind='in' GROUP BY e.id HAVING count(DISTINCT coalesce(b.paid_at, t.paid_at))>1 OR count(DISTINCT coalesce(b.payment_method, t.payment_method))>1"
    )
    assert mixed == [], "mỗi dòng thu là một lần nhận tiền"
    wrong_time = await fetch(
        "SELECT e.id FROM booking.payment_entry e JOIN booking.payment_entry_item i ON i.entry_id=e.id "
        "LEFT JOIN booking.booking b ON b.id=i.booking_id LEFT JOIN booking.ticket t ON t.id=i.ticket_id "
        "WHERE (e.kind='in' AND e.occurred_at <> coalesce(b.paid_at, t.paid_at)) OR (e.kind='refund' AND e.occurred_at <> coalesce(b.cancelled_at, t.cancelled_at))"
    )
    assert wrong_time == [], "thu = paid_at, hoàn = cancelled_at"
    wrong_source = await fetch(
        "SELECT id FROM booking.payment_entry WHERE (method = 'online_transfer') <> (source = 'online')"
    )
    assert wrong_source == []

    # P4: số dòng = số khóa gộp (khóa BE công bố trong handoff)
    in_keys = {(r["order"], r["paid_at"], r["method"], r["who"]) for r in counted(bookings)} | {
        ("ticket", r["ref"], r["paid_at"], r["method"], r["who"]) for r in counted(tickets)
    }
    rf_keys = {
        (r["order"], r["cancelled_at"], r["method"], "Admin")
        for r in bookings
        if r.get("refund", 0) > 0
    } | {
        ("ticket", r["ref"], r["cancelled_at"], r["method"], "Admin")
        for r in tickets
        if r.get("refund", 0) > 0
    }
    [(n_in, n_rf)] = await fetch(
        "SELECT count(*) FILTER (WHERE kind='in'), count(*) FILTER (WHERE kind='refund') FROM booking.payment_entry"
    )
    assert (n_in, n_rf) == (len(in_keys), len(rf_keys)), "số dòng sổ = số lần nhận / hoàn tiền"

    # P7: down / up / check
    before_rows = (await fetch("SELECT count(*) FROM booking.payment_entry"))[0][0]
    await alembic(command.downgrade, BEFORE)
    assert (await fetch("SELECT count(*) FROM booking.booking"))[0][0] == len(bookings)
    assert (await fetch("SELECT count(*) FROM booking.ticket"))[0][0] == len(tickets)
    await alembic(command.upgrade, "head")
    assert (await fetch("SELECT count(*) FROM booking.payment_entry"))[0][0] == before_rows, (
        "nâng lại cho cùng kết quả"
    )
    await alembic(lambda cfg, _rev: command.check(cfg), "head")


async def test_empty_database_and_double_upgrade_are_clean(mig_db):
    await alembic(command.upgrade, TARGET)
    assert (await fetch("SELECT count(*) FROM booking.payment_entry"))[0][0] == 0
    await alembic(command.downgrade, BEFORE)
    await alembic(command.upgrade, TARGET)
    await alembic(command.upgrade, "head")
    await alembic(lambda cfg, _rev: command.check(cfg), "head")
