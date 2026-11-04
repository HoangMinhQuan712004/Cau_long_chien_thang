"""Dữ liệu mẫu cho link dev – khu hội viên có số liệu để xem (T-034). **Chỉ dev / local.**

    DEMO_MEMBER_PASSWORD=... python -m app.scripts.seed_demo   # xóa mẫu cũ rồi tạo lại
    python -m app.scripts.seed_demo --clear                     # chỉ xóa dữ liệu mẫu

- ``ENV=production`` -> từ chối (exit 2), không ghi gì.
- SĐT trong dải mẫu ``09990000xx`` đang thuộc hồ sơ / tài khoản thật -> dừng (exit 3).
- Script chỉ **điều phối**: tạo / xóa qua ``api`` của từng module (members, auth, booking_engine,
  play_rooms, records, member_inbox). Booking mẫu vẫn đi qua exclusion constraint.
- Dấu mẫu: họ tên "Mẫu · ", SĐT ``09990000xx``, sự kiện "[Mẫu]", số đo ``source_ref`` "demo:".
- ``DEMO_MEMBER_PHONE`` (tùy chọn, bổ sung 04/11): SĐT đăng nhập của "Mẫu · Hội viên 01" do người
  dùng chọn; số đó đang thuộc hồ sơ / tài khoản thật -> dừng (exit 3). Chỉ in SĐT đã che.
- ``DEMO_VIDEO_URLS`` (tùy chọn): link video (https, cách nhau bởi dấu phẩy / khoảng trắng) gắn vào
  các lần phá kỷ lục mẫu. Code không chứa link video của bên thứ ba.
- ``DEMO_MEMBER_PASSWORD``: mật khẩu của "Mẫu · Hội viên 01" và "02" (không in, không log). Thiếu
  biến -> hai hồ sơ này không có tài khoản đăng nhập. Hội viên mẫu còn lại có tài khoản liên kết
  với mật khẩu ngẫu nhiên không ai biết (để hiện trên Bảng xếp hạng / phòng chơi).
- Chạy lại = xóa dữ liệu mẫu cũ rồi tạo mới (không nhân đôi; phòng "hôm nay" luôn đúng ngày).
"""

import argparse
import asyncio
import os
import secrets
import sys
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.errors import AppError
from app.core.privacy import mask_phone
from app.modules.auth import api as auth
from app.modules.booking_engine import api as engine
from app.modules.member_inbox import api as inbox
from app.modules.members import api as members
from app.modules.play_rooms import api as rooms
from app.modules.records import api as records

EXIT_PRODUCTION = 2
EXIT_FOREIGN = 3
EXIT_BAD_PHONE = 4
MAX_VIDEOS = 3
DEMO_RANGE = range(1, 100)  # 0999000001 … 0999000099

# 12 hội viên: phủ 8 bậc + 2 "Chưa xếp hạng"; 05 và 09 ẩn danh trên Bảng xếp hạng
SPECS = [
    members.DemoMemberSpec(1, "Khá", True, "Mẫu 01", "Yonex Astrox 88D"),
    members.DemoMemberSpec(2, "Yếu", True, "Mẫu 02"),
    members.DemoMemberSpec(3, "Trung bình yếu", True),
    members.DemoMemberSpec(4, "Trung bình -", True),
    members.DemoMemberSpec(5, "Trung bình", False),
    members.DemoMemberSpec(6, "Trung bình +", True),
    members.DemoMemberSpec(7, "Bán chuyên", True),
    members.DemoMemberSpec(8, "Chuyên nghiệp", True),
    members.DemoMemberSpec(9, "Khá", False),
    members.DemoMemberSpec(10, "Trung bình", True),
    members.DemoMemberSpec(11, None, True),
    members.DemoMemberSpec(12, None, True),
]
LOGIN_MEMBERS = (1, 2)  # có mật khẩu DEMO_MEMBER_PASSWORD
PAST_DAYS = (1, 3, 8, 15, 23, 34, 47)  # ~7 buổi trong 2 tháng gần nhất (có buổi tháng này)


def _phones() -> list[str]:
    return [members.demo_phone(n) for n in DEMO_RANGE]


def _snapshot(m: members.DemoMember) -> engine.CustomerSnapshot:
    return engine.CustomerSnapshot(
        ref_id=str(m.customer_id),
        kind="member",
        display_name=m.full_name,
        phone=m.phone,
        member_code=m.member_code,
        tier=m.tier,
    )


async def purge(session: AsyncSession) -> dict[str, int]:
    """Xóa mọi dữ liệu có dấu mẫu, theo thứ tự phụ thuộc. Không commit."""
    ids = await members.demo_member_ids(session)
    phones = sorted(set(_phones()) | set(await members.demo_member_phones(session)))
    codes = await engine.demo_booking_codes(session, phones)
    counts = {"rooms": await rooms.purge_demo(session, codes, ids)}
    counts["notifications"] = await inbox.purge_for(session, ids)
    counts["speed_records"] = await records.purge_demo(session)
    for name, n in (await engine.purge_demo(session, phones)).items():
        counts[name] = n
    counts["accounts"] = await auth.purge_demo(session)
    counts["members"] = await members.purge_demo(session)
    return counts


def _local(now: datetime) -> datetime:
    return now.astimezone(settings.tz)


async def _past_sessions(
    session: AsyncSession, people: list[members.DemoMember], now: datetime, rng
) -> tuple[int, int]:
    """Buổi đã qua: booking đã thanh toán (tiền mặt / QR) + phòng đóng có 3–6 trận finished."""
    hosts = [people[0], people[0], people[1], people[0], people[5], people[0], people[6]]
    sessions = matches_total = 0
    for i, days in enumerate(PAST_DAYS):
        host = hosts[i]
        day = _local(now).date() - timedelta(days=days)
        hour = 7 + i % 4
        end = datetime(day.year, day.month, day.day, hour + 1, tzinfo=settings.tz)
        payment = engine.DemoPayment(
            method="cash" if i % 2 else "online_transfer", paid_at=end.astimezone(UTC)
        )
        code = await engine.seed_demo_booking(
            session,
            _snapshot(host),
            day,
            [hour, hour + 1, 6, 12],
            channel="counter" if i % 2 else "online",
            payment=payment,
        )
        if code is None:
            continue
        others = [p for p in people if p.customer_id != host.customer_id]
        pool = [host, *rng.sample(others, rng.randint(3, 5))]
        if people[0] not in pool:
            pool[-1] = people[0]
        ids = [p.customer_id for p in pool]
        games = []
        start = end - timedelta(hours=1)
        for g in range(rng.randint(3, 6)):
            size = 2 if g % 2 == 0 else 1  # 2 vs 2 và 1 vs 1 xen kẽ
            players = rng.sample(ids, size * 2)
            if g % 3 == 0 and people[0].customer_id not in players:
                players[0] = people[0].customer_id  # tài khoản mẫu 01 có tham gia (không trùng)
            a, b = players[:size], players[size:]
            win = rng.randint(21, 25)
            lose = rng.randint(10, win - 2)
            sa, sb = (win, lose) if rng.random() < 0.5 else (lose, win)
            games.append(
                rooms.DemoMatch(
                    a,
                    b,
                    sa,
                    sb,
                    start + timedelta(minutes=10 * g),
                    start + timedelta(minutes=10 * g + 9),
                )
            )
        await rooms.seed_demo_room(session, code, member_ids=ids, matches=games, close=True)
        sessions += 1
        matches_total += len(games)
    return sessions, matches_total


async def _rooms_today(
    session: AsyncSession, people: list[members.DemoMember], now: datetime
) -> int:
    """5 phòng hôm nay (hoặc ngày mai nếu đã muộn): 01 làm Host ("Tiếp theo"); không giới hạn,
    "Trung bình – Khá", "từ Khá"; thêm 1 phòng còn chỗ không có 01 ("Phòng đang trống")."""
    local = _local(now)
    day: date = local.date()
    hours = list(range(max(local.hour + 1, 6), 22))
    if len(hours) < 3:
        day, hours = day + timedelta(days=1), list(range(8, 22))
    p = {n: people[n - 1] for n in range(1, 13)}
    plans = [
        (p[1], None, None, [p[2], p[12]], [], "counter", None),
        (p[3], None, None, [p[1], p[6]], [p[10]], "counter", None),
        (p[4], "Trung bình", "Khá", [p[1], p[10]], [p[6]], "online", "online_transfer"),
        (p[5], "Khá", None, [p[7], p[8]], [p[9]], "online", "online_transfer"),
        (p[6], None, None, [p[11]], [], "counter", None),
    ]
    made = 0
    for i, (host, low, high, joined, pending, channel, method) in enumerate(plans):
        payment = engine.DemoPayment(method=method, paid_at=now) if method else None
        code = await engine.seed_demo_booking(
            session,
            _snapshot(host),
            day,
            hours[i:] + hours[:i],
            channel=channel,
            payment=payment,
            min_tier=low,
            max_tier=high,
        )
        if code is None:
            continue
        await rooms.seed_demo_room(
            session,
            code,
            member_ids=[m.customer_id for m in joined],
            pending_join=[m.customer_id for m in pending],
        )
        made += 1
    return made


async def _events(session: AsyncSession, people: list[members.DemoMember], now: datetime) -> int:
    today = _local(now).date()
    p = {n: people[n - 1] for n in range(1, 13)}
    plans = [  # (tên, sau n ngày, giá, người mua, sức chứa)
        ("Giao lưu cuối tuần", 2, 60_000, [p[1], p[3], p[6]], 16),
        ("Giải đôi nam nữ", 5, 80_000, [p[2], p[7], p[8], p[9]], 4),  # đã đủ chỗ
    ]
    made = 0
    for name, days, price, buyers, capacity in plans:
        code = await engine.seed_demo_event(
            session,
            name,
            today + timedelta(days=days),
            [18, 17, 19, 16, 9],
            capacity,
            price,
            [_snapshot(b) for b in buyers],
            now,
        )
        made += code is not None
    return made


DEMO_ACTOR = engine.Actor(type="system", id=None, label="Dữ liệu mẫu")


async def _recurring(session: AsyncSession, people: list[members.DemoMember], now: datetime) -> int:
    """Đơn định kỳ qua đường đặt thật (all-or-nothing, exclusion constraint): 01 chưa thu (2 thứ ×
    4 tuần ≈ 8 buổi, giảm 10%); 03 đã thu cả đơn (1 thứ × 4 tuần)."""
    courts = [r for r in (await engine.list_resources(session)).items if r.is_active]
    start = _local(now).date() + timedelta(days=1)
    plans = [
        (people[0], [start.isoweekday(), (start + timedelta(days=3)).isoweekday()], 10, False),
        (people[2], [(start + timedelta(days=1)).isoweekday()], 0, True),
    ]
    made = 0
    for who, weekdays, pct, collect in plans:
        done = None
        for court in courts:
            for hour in (6, 7, 21, 5, 20):
                data = engine.RecurringIn(
                    resource_code=court.code,
                    weekdays=weekdays,
                    start_hour=hour,
                    end_hour=hour + 1,
                    date_from=start,
                    date_to=start + timedelta(days=27),
                    discount_pct=pct,
                )
                try:
                    done = await engine.create_recurring(session, DEMO_ACTOR, data, _snapshot(who))
                except AppError:  # trùng / ngoài giờ -> thử khung khác
                    continue
                break
            if done is not None:
                break
        if done is None:
            continue
        if collect:
            await engine.collect_order(
                session, DEMO_ACTOR, done.order_code, engine.OrderCollectIn(method="cash")
            )
        made += 1
    return made


async def seed(
    session: AsyncSession,
    password: str | None,
    first_phone: str | None = None,
    video_urls: list[str] | None = None,
) -> dict[str, int | list[str]]:
    rng = secrets.SystemRandom()
    now = datetime.now(UTC)
    people = await members.seed_demo_members(session, SPECS, first_phone)
    logins: list[str] = []
    accounts = 0
    for spec, m in zip(SPECS, people, strict=True):
        known = spec.n in LOGIN_MEMBERS
        if known and password is None:
            continue  # thiếu DEMO_MEMBER_PASSWORD -> hồ sơ không có tài khoản đăng nhập
        await auth.create_demo_account(session, m.phone, m.full_name, password if known else None)
        accounts += 1
        if known:
            logins.append(mask_phone(m.phone) or "")
    sessions, matches = await _past_sessions(session, people, now, rng)
    return {
        "members": len(people),
        "accounts": accounts,
        "past_sessions": sessions,
        "matches": matches,
        "rooms_today": await _rooms_today(session, people, now),
        "events": await _events(session, people, now),
        "recurring_orders": await _recurring(session, people, now),
        "speed_records": await records.seed_demo_speeds(
            session, [m.customer_id for m in people], now
        ),
        # 3 lần phá kỷ lục cụm (Kỷ lục mới, T-036), 01 có một lần; gắn video nếu có
        "record_breaks": await records.seed_demo_breaks(
            session,
            [people[6].customer_id, people[0].customer_id, people[7].customer_id],
            now,
            video_urls or [],
        ),
        "videos": len(video_urls or []),
        "login_phones": logins,
    }


async def run(
    clear: bool,
    password: str | None,
    first_phone: str | None = None,
    video_urls: list[str] | None = None,
) -> int:
    async with SessionLocal() as session:
        foreign = await members.demo_foreign_phones(
            session, first_phone
        ) + await auth.demo_foreign_phones(session, first_phone)
        if foreign:
            masked = ", ".join(sorted({mask_phone(p) or "" for p in foreign}))
            print(f"Dừng: SĐT mẫu đang thuộc hồ sơ / tài khoản thật ({masked}).", file=sys.stderr)
            return EXIT_FOREIGN
        removed = await purge(session)
        if clear:
            await session.commit()
            print("Đã xóa dữ liệu mẫu: " + ", ".join(f"{k}={v}" for k, v in removed.items()))
            return 0
        created = await seed(session, password, first_phone, video_urls)
        await session.commit()
    logins = created.pop("login_phones")
    print("Đã tạo dữ liệu mẫu: " + ", ".join(f"{k}={v}" for k, v in created.items()))
    if logins:
        print("Tài khoản đăng nhập mẫu (SĐT che): " + ", ".join(logins))
    else:
        print("Không đặt DEMO_MEMBER_PASSWORD: chưa có tài khoản đăng nhập mẫu.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dữ liệu mẫu cho link dev (không dùng production)")
    parser.add_argument("--clear", action="store_true", help="Chỉ xóa dữ liệu mẫu")
    args = parser.parse_args(argv)
    if settings.is_production:
        print("Từ chối: không tạo / xóa dữ liệu mẫu khi ENV=production.", file=sys.stderr)
        return EXIT_PRODUCTION
    password = os.environ.get("DEMO_MEMBER_PASSWORD") or None
    raw_phone = (os.environ.get("DEMO_MEMBER_PHONE") or "").strip()
    first_phone = None
    if raw_phone:
        first_phone = members.normalize_phone(raw_phone)
        if not members.PHONE_RE.match(first_phone):
            print("Dừng: DEMO_MEMBER_PHONE không phải SĐT hợp lệ (10 số).", file=sys.stderr)
            return EXIT_BAD_PHONE
    return asyncio.run(run(args.clear, password, first_phone, video_urls_from_env()))


def video_urls_from_env() -> list[str]:
    """``DEMO_VIDEO_URLS``: link https cách nhau bởi dấu phẩy / khoảng trắng, lấy tối đa 3."""
    raw = os.environ.get("DEMO_VIDEO_URLS") or ""
    urls = [u for u in raw.replace(",", " ").split() if u.startswith("https://")]
    return urls[:MAX_VIDEOS]


if __name__ == "__main__":
    raise SystemExit(main())
