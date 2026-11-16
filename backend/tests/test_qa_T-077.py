# ruff: noqa: E501
"""QA T-077 (API): phiên Admin/NV trượt 30 ngày, refresh token khách, nhắc giờ khi đặt sát giờ.

Góc nhìn độc lập với ``test_session_sliding.py`` / ``test_web_push_events.py`` của BACKEND: biên thời gian đến từng giây
(còn 1 ngày vẫn vào, quá hạn 1 giây hết, phiên hết hạn không "sống lại" nhờ request, mốc gia hạn 59'59'' / 1h00'01'',
20 request song song một lần gia hạn), refresh token sai (không cookie, rác, token truy cập, ``token_version`` tăng) không cấp
token mới, luật nhắc sát giờ theo bảng spec (``created_at`` start−59'59'' và start−20'01'' nhắc ở start−15'; đúng 20', 19'59'',
5' không nhắc; cửa sổ start−15' … start−5', đúng 5' bỏ), một khối nhắc một lần, đặt từ hôm trước không nhắc thêm lần 15',
vé sự kiện sát giờ, hộp thông báo vẫn có khi chưa có thiết bị push.
"""

import asyncio
import importlib
import re
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy import event, select, update

from app.core.config import settings
from app.core.db import SessionLocal, engine
from app.modules.auth.models import AdminSession, User
from app.modules.booking_engine.models import EventSession, Ticket
from app.modules.member_area import handlers as member_area
from app.modules.member_inbox.models import MemberNotification
from tests.conftest import API, ENQUEUED_JOBS, PUSH, _client, idem, new_customer, sign_in
from tests.conftest import push_testing as testing
from tests.helpers_booking import member
from tests.test_auth import PASSWORD, create_staff
from tests.test_counter_qr import FD
from tests.test_web_push import _user_id
from tests.test_web_push_events import _backdate, device, flush, inbox_texts, member_block, to

t76 = importlib.import_module("tests.test_qa_T-076_events")
clock, event_today, start_of, people = t76.clock, t76.event_today, t76.start_of, t76.people

IDLE_DAYS = settings.ADMIN_SESSION_IDLE_DAYS


def admin_cookie(r):
    return next(
        (v for v in r.headers.get_list("set-cookie") if v.startswith("admin_session=")), None
    )


def cookie_max_age(r) -> int | None:
    cookie = admin_cookie(r)
    match = re.search(r"max-age=(\d+)", cookie.lower()) if cookie else None
    return int(match.group(1)) if match else None


def renewals(updates: list[str]) -> int:
    """Số lần GHI THẬT hạn phiên: câu UPDATE không điều kiện (ghi lại ``expires_at`` đã gia hạn). Câu UPDATE có điều kiện
    ``expires_at < …`` mà thua cuộc đua thì không đổi dòng nào nên không tính."""
    return sum("expires_at <" not in u for u in updates)


@contextmanager
def admin_session_updates():
    """Ghi lại các câu UPDATE bảng admin_sessions đã gửi lên DB trong khối."""
    seen: list[str] = []

    def before(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("UPDATE") and "admin_sessions" in statement:
            seen.append(statement)

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        yield seen
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before)


async def session_row(user_id: int) -> AdminSession:
    async with SessionLocal() as s:
        return await s.scalar(
            select(AdminSession)
            .where(AdminSession.user_id == user_id, AdminSession.revoked_at.is_(None))
            .order_by(AdminSession.id.desc())
            .limit(1)
        )


async def set_expiry(row_id: int, expires_at: datetime) -> None:
    async with SessionLocal() as s:
        await s.execute(
            update(AdminSession).where(AdminSession.id == row_id).values(expires_at=expires_at)
        )
        await s.commit()


# ---------------------------------------------------------------- B: phiên Admin/NV trượt (AC5–AC7)


async def test_ac5_idle_boundaries_still_valid_then_expired_and_never_revived(admin):
    nv = await create_staff(admin, "QA Phiên Biên")
    async with _client() as c:
        await sign_in(c, nv["username"], PASSWORD)
        row = await session_row(nv["id"])
        # Còn 30 giây tới hết hạn trượt: vẫn vào được và được gia hạn
        await set_expiry(row.id, datetime.now(UTC) + timedelta(seconds=30))
        r = await c.get(f"{API}/admin/auth/me")
        assert r.status_code == 200 and admin_cookie(r) is not None
        # 29 ngày không dùng (còn 1 ngày): vào được
        await set_expiry(row.id, datetime.now(UTC) + timedelta(days=1))
        assert (await c.get(f"{API}/admin/auth/me")).status_code == 200
        # Quá hạn 1 giây: 401 expired, và các request sau vẫn 401 (không tự sống lại)
        await set_expiry(row.id, datetime.now(UTC) - timedelta(seconds=1))
        for _ in range(2):
            r = await c.get(f"{API}/admin/auth/me")
            assert r.status_code == 401 and r.json()["detail"]["reason"] == "expired"
            cookie = admin_cookie(r)
            assert cookie is None or "max-age=0" in cookie.lower()
        async with SessionLocal() as s:
            expires = await s.scalar(
                select(AdminSession.expires_at).where(AdminSession.id == row.id)
            )
        assert expires < datetime.now(UTC), "phiên đã hết hạn không được gia hạn lại"


async def test_ac7_renewal_threshold_59m59s_is_not_written_1h01s_is(admin):
    nv = await create_staff(admin, "QA Phiên Ngưỡng")
    async with _client() as c:
        await sign_in(c, nv["username"], PASSWORD)
        row = await session_row(nv["id"])
        full = timedelta(days=IDLE_DAYS)
        under = datetime.now(UTC) + full - timedelta(minutes=59, seconds=59)
        await set_expiry(row.id, under)
        with admin_session_updates() as updates:
            r = await c.get(f"{API}/admin/auth/me")
        assert r.status_code == 200 and updates == [], "chưa đủ 1 giờ: không ghi DB"
        assert (await session_row(nv["id"])).expires_at == under, "expires_at không đổi"
        remaining = (under - datetime.now(UTC)).total_seconds()
        age = cookie_max_age(r)  # mọi request đều gửi lại cookie, nhưng không bao giờ dài hơn DB
        assert age is not None and 0 < age <= remaining and age >= remaining - 5, (age, remaining)
        over = datetime.now(UTC) + full - timedelta(hours=1, seconds=1)
        await set_expiry(row.id, over)
        with admin_session_updates() as updates:
            r = await c.get(f"{API}/admin/auth/me")
        assert r.status_code == 200 and renewals(updates) == 1, "quá 1 giờ: gia hạn đúng một lần"
        renewed = (await session_row(nv["id"])).expires_at
        assert renewed > over + timedelta(minutes=59)
        age = cookie_max_age(r)
        assert age is not None and age <= (renewed - datetime.now(UTC)).total_seconds() + 1


async def _parallel_on_stale_session(admin, n: int, name: str) -> None:
    nv = await create_staff(admin, name)
    async with _client() as c:
        await sign_in(c, nv["username"], PASSWORD)
        row = await session_row(nv["id"])
        old = datetime.now(UTC) + timedelta(days=3)
        await set_expiry(row.id, old)
        with admin_session_updates() as updates:
            rs = await asyncio.gather(*(c.get(f"{API}/admin/auth/me") for _ in range(n)))
        assert {r.status_code for r in rs} == {200}
        assert renewals(updates) == 1, (
            f"{n} request song song chỉ được gia hạn một lần ({len(updates)} câu UPDATE)"
        )
        renewed = (await session_row(nv["id"])).expires_at
        assert renewed > datetime.now(UTC) + timedelta(days=29), "gia hạn tới ~30 ngày"
        for r in rs:  # mỗi cookie gửi lại không bao giờ dài hơn hạn thật trong DB
            age = cookie_max_age(r)
            assert (
                age is not None and 0 < age <= (renewed - datetime.now(UTC)).total_seconds() + 5
            ), age


async def test_ac7_eight_parallel_requests_on_a_stale_session_renew_exactly_once(admin):
    await _parallel_on_stale_session(admin, 8, "QA Phiên Song Song 8")


async def test_ac7_twenty_parallel_requests_on_a_stale_session_do_not_starve_the_db_pool(admin):
    await _parallel_on_stale_session(admin, 20, "QA Phiên Song Song 20")


# ---------------------------------------------------------------- A: refresh token (AC3–AC4, phía BE)


async def test_ac3_bad_refresh_tokens_never_mint_a_new_pair():
    for cookie in (None, "rac", "a.b.c", "x" * 400):
        async with _client() as c:
            if cookie:
                c.cookies.set("refresh_token", cookie)
            r = await c.post(f"{API}/auth/refresh")
            assert r.status_code == 401, (cookie, r.status_code)
            live = [
                v
                for v in r.headers.get_list("set-cookie")
                if v.startswith(("access_token=", "refresh_token="))
                and "max-age=0" not in v.lower()
            ]
            assert live == [], "token sai không được nhận cookie mới"
    async with new_customer() as c:  # token truy cập không dùng làm refresh token
        c.cookies.set("refresh_token", c.cookies.get("access_token"))
        assert (await c.post(f"{API}/auth/refresh")).status_code == 401


async def test_ac3_token_version_bump_kills_old_and_refreshed_tokens_alike():
    async with new_customer() as c:
        old = c.cookies.get("refresh_token")
        assert (await c.post(f"{API}/auth/refresh")).status_code == 200
        uid = await _user_id(c)
        async with SessionLocal() as s:  # như đổi mật khẩu / khóa tài khoản
            await s.execute(
                update(User).where(User.id == uid).values(token_version=User.token_version + 1)
            )
            await s.commit()
        async with _client() as stale:
            stale.cookies.set("refresh_token", old)
            assert (await stale.post(f"{API}/auth/refresh")).status_code == 401
        assert (await c.post(f"{API}/auth/refresh")).status_code == 401, (
            "token mới cũng hết hiệu lực"
        )


# ---------------------------------------------------------------- C: nhắc sát giờ (AC8–AC9)


async def run_reminders(now: datetime) -> None:
    await member_area.send_reminders(now)
    await testing.drain(ENQUEUED_JOBS)


async def test_ac8_late_booking_rule_table_boundaries(admin, staff, people):
    hv = await people("QA Hội Viên Sát Giờ")
    ep = await device(hv.client)
    offsets = {
        "t5959": timedelta(minutes=59, seconds=59),
        "t2001": timedelta(minutes=20, seconds=1),
        "t2000": timedelta(minutes=20),
        "t1959": timedelta(minutes=19, seconds=59),
        "t0500": timedelta(minutes=5),
    }
    blocks = {k: await member_block(staff, admin, hv, hour=18) for k in offsets}
    start = await start_of(blocks["t5959"]["code"])
    for k, off in offsets.items():
        await _backdate(blocks[k]["code"], start - off)
    await flush()
    PUSH.clear()

    def got(k):
        return [s for s in to(ep) if blocks[k]["order_code"] in s.body]

    await run_reminders(start - timedelta(minutes=16))
    assert PUSH.sent == [], "chưa tới start − 15'"
    await run_reminders(start - timedelta(minutes=15))
    assert len(got("t5959")) == 1 and len(got("t2001")) == 1, "ca sát giờ nhắc ở start − 15'"
    assert not got("t2000") and not got("t1959") and not got("t0500"), "còn ≤ 20' không nhắc"
    for delta in (
        timedelta(minutes=10),
        timedelta(minutes=5, seconds=1),
        timedelta(minutes=5),
        timedelta(minutes=1),
    ):
        await run_reminders(start - delta)
    assert len(got("t5959")) == 1 and len(got("t2001")) == 1, "cron chạy lại không nhắc thêm"
    assert not got("t2000") and not got("t1959") and not got("t0500")
    assert {s.title for s in to(ep)} == {"Sắp đến giờ chơi"}


async def test_ac8_late_window_closes_exactly_at_start_minus_5_minutes(admin, staff, people):
    hv = await people("QA Hội Viên Cửa Sổ")
    ep = await device(hv.client)
    first = await member_block(staff, admin, hv, hour=18)
    start = await start_of(first["code"])
    await _backdate(first["code"], start - timedelta(minutes=45))
    await flush()
    PUSH.clear()
    await run_reminders(
        start - timedelta(minutes=5, seconds=1)
    )  # worker chạy muộn, còn trong cửa sổ
    assert len([s for s in to(ep) if first["order_code"] in s.body]) == 1
    second = await member_block(staff, admin, hv, hour=18)
    await _backdate(second["code"], start - timedelta(minutes=45))
    await flush()
    await run_reminders(start - timedelta(minutes=5))  # đúng 5 phút: bỏ
    await run_reminders(start - timedelta(minutes=2))
    assert [s for s in to(ep) if second["order_code"] in s.body] == []


async def test_ac8_booked_the_day_before_is_reminded_at_60_minutes_only(admin, staff, people):
    hv = await people("QA Hội Viên Thường")
    ep = await device(hv.client)
    b = await member_block(staff, admin, hv, hour=18)
    start = await start_of(b["code"])
    await _backdate(b["code"], start - timedelta(hours=20))
    await flush()
    PUSH.clear()
    await run_reminders(start - timedelta(minutes=60))
    for minutes in (30, 15, 14, 10, 5):
        await run_reminders(start - timedelta(minutes=minutes))
    assert len(to(ep)) == 1, "nhắc 60 phút trước, không nhắc thêm lần 15 phút"


async def test_ac8_ac9_late_ticket_reminder_and_inbox_without_any_device(admin, people, clock):
    hv = await people("QA Hội Viên Vé Sát Giờ")  # không bật thiết bị push
    ev = await event_today(admin)
    r = await admin.post(
        f"{FD}/sessions/{ev['code']}/tickets", json={"customer": member(hv.code)}, headers=idem()
    )
    assert r.status_code == 201, r.text
    code = r.json()["code"]
    async with SessionLocal() as s:
        start = await s.scalar(select(EventSession.start_at).where(EventSession.code == ev["code"]))
        await s.execute(
            update(Ticket)
            .where(Ticket.code == code)
            .values(created_at=start - timedelta(minutes=40))
        )
        await s.commit()
    PUSH.clear()
    attempts = len(PUSH.attempts)
    await run_reminders(start - timedelta(minutes=16))
    assert await inbox_texts(hv.customer_id, "booking.reminder") == []
    await run_reminders(start - timedelta(minutes=15))
    await run_reminders(start - timedelta(minutes=12))
    texts = await inbox_texts(hv.customer_id, "booking.reminder")
    assert texts == [f"{ev['name']} · 9h–11h hôm nay · {code}"], texts
    assert PUSH.sent == [] and len(PUSH.attempts) == attempts, "chưa có thiết bị: hộp vẫn có (AC9)"
    async with SessionLocal() as s:
        rows = list(
            await s.scalars(
                select(MemberNotification).where(
                    MemberNotification.customer_id == hv.customer_id,
                    MemberNotification.kind == "booking.reminder",
                )
            )
        )
    assert len(rows) == 1
