"""Dựng dữ liệu cho test Báo cáo: mỗi test một tenant riêng ⇒ số liệu không lẫn với test khác."""

import random
import uuid
from datetime import date, datetime, time, timedelta

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.booking_engine import ledger
from app.modules.booking_engine.dto import Actor
from app.modules.booking_engine.models import (
    DEFAULT_TENANT_SETTINGS,
    Allocation,
    Booking,
    BookingOrder,
    EventSession,
    Resource,
    ResourceSchedule,
    ResourceType,
    Tenant,
    Ticket,
)
from app.modules.members.models import Customer
from app.modules.members.profiles import next_code as next_member_code
from tests.conftest import unique_phone

CUSTOMER = {
    "customer_ref": "test-report",
    "customer_kind": "temp",
    "customer_name": "Khách báo cáo",
    "customer_phone": "0900000001",
}
BY_TEST = {"created_by_type": "system", "created_by_label": "Test"}


def at(day: date, hour: float) -> datetime:
    return datetime.combine(day, time(), settings.tz) + timedelta(hours=hour)


def _code() -> str:
    return f"RP-{uuid.uuid4().hex[:12].upper()}"


TEST_ACTOR = Actor(type="system", label="Test")


def _paid(status: str, start: datetime) -> dict:
    """Đã thu: tiền về đúng lúc bắt đầu chơi -> ngày tiền về = ngày chơi, so cùng mốc như cũ."""
    if status == "paid":
        return {"payment_status": "paid", "payment_method": "cash", "paid_at": start}
    if status == "uncollectible":
        return {"payment_status": "uncollectible", "uncollectible_reason": "Khách bỏ về"}
    return {"payment_status": "unpaid"}


class Venue:
    """Một cụm sân riêng (tenant mới) để dựng sân, booking, sự kiện."""

    def __init__(self, s: AsyncSession, tenant_id: int, type_id: int):
        self.s, self.tid, self.type_id = s, tenant_id, type_id
        self.courts: dict[str, Resource] = {}

    @classmethod
    async def create(cls, s: AsyncSession) -> "Venue":
        tid = random.randint(1000, 32000)
        while await s.get(Tenant, tid) is not None:
            tid = random.randint(1000, 32000)
        s.add(
            Tenant(
                id=tid,
                code=f"rp-{tid}",
                name="Cụm test báo cáo",
                timezone=settings.TIMEZONE,
                settings=dict(DEFAULT_TENANT_SETTINGS),
                version=1,
            )
        )
        await s.flush()
        rtype = ResourceType(tenant_id=tid, code="thuong", name="Thường")
        s.add(rtype)
        await s.flush()
        return cls(s, tid, rtype.id)

    async def court(
        self,
        code: str,
        open_hour: float = 5,
        close_hour: float = 22,
        *,
        active: bool = True,
        since: date = date(2019, 1, 1),
    ) -> Resource:
        row = Resource(
            tenant_id=self.tid,
            code=code,
            name=f"Sân {code}",
            resource_type_id=self.type_id,
            is_active=active,
        )
        self.s.add(row)
        await self.s.flush()
        self.courts[code] = row
        await self.hours(code, open_hour, close_hour, since)
        return row

    async def hours(self, code: str, open_hour: float, close_hour: float, since: date) -> None:
        """Thêm một phiên bản giờ mở cửa có hiệu lực từ ``since``."""
        self.s.add(
            ResourceSchedule(
                tenant_id=self.tid,
                resource_id=self.courts[code].id,
                effective_from=since,
                open_minute=int(open_hour * 60),
                close_minute=int(close_hour * 60),
                peak_bands=[],
                created_by_label="Test",
            )
        )
        await self.s.flush()

    def _alloc(self, code: str, day: date, hour: int, hours: int, **owner) -> None:
        self.s.add(
            Allocation(
                tenant_id=self.tid,
                resource_id=self.courts[code].id,
                time_range=Range(at(day, hour), at(day, hour + hours), bounds="[)"),
                active=True,
                **owner,
            )
        )

    async def booking(
        self, code: str, day: date, hour: int, amount: int, *, hours: int = 1, status="paid"
    ) -> Booking:
        order = BookingOrder(
            tenant_id=self.tid,
            code=_code(),
            play_date=day,
            channel="counter",
            created_by_label="Test",
            **CUSTOMER,
        )
        self.s.add(order)
        await self.s.flush()
        row = Booking(
            tenant_id=self.tid,
            order_id=order.id,
            seq=1,
            code=f"{order.code}-01",
            source="counter",
            resource_id=self.courts[code].id,
            play_date=day,
            start_at=at(day, hour),
            end_at=at(day, hour + hours),
            amount=amount,
            **_paid(status, at(day, hour)),
            **BY_TEST,
            **CUSTOMER,
        )
        self.s.add(row)
        await self.s.flush()
        await self._ledger([row])
        self._alloc(code, day, hour, hours, kind="booking", booking_id=row.id)
        await self.s.flush()
        return row

    async def event(
        self,
        codes: list[str],
        day: date,
        hour: int,
        tickets: list[int],
        *,
        hours: int = 2,
        status: str = "paid",
    ) -> EventSession:
        ev = EventSession(
            tenant_id=self.tid,
            code=_code(),
            name="Sự kiện báo cáo",
            play_date=day,
            start_at=at(day, hour),
            end_at=at(day, hour + hours),
            capacity=99,
            ticket_price=0,
            **BY_TEST,
        )
        self.s.add(ev)
        await self.s.flush()
        for code in codes:
            self._alloc(code, day, hour, hours, kind="session", session_id=ev.id)
        rows = []
        for seq, amount in enumerate(tickets, start=1):
            rows.append(
                Ticket(
                    tenant_id=self.tid,
                    session_id=ev.id,
                    seq=seq,
                    code=f"{ev.code}-V{seq:02d}",
                    source="counter",
                    amount=amount,
                    **_paid(status, at(day, hour)),
                    **BY_TEST,
                    **CUSTOMER,
                )
            )
        self.s.add_all(rows)
        await self.s.flush()
        for t in rows:
            await self._ledger([t])
        return ev

    async def _ledger(self, rows: list) -> None:
        """Sổ tiền vào (T-057): báo cáo đọc tiền từ sổ, không từ dòng booking / vé."""
        paid = [r for r in rows if r.payment_status == "paid"]
        if paid:
            await ledger.record_in(
                self.s, self.tid, paid, method="cash", occurred_at=paid[0].paid_at, actor=TEST_ACTOR
            )


async def add_customer(
    s: AsyncSession, created_at: datetime, phones: list[str], *, member: bool = True
) -> None:
    """Hồ sơ khách tạo lúc ``created_at``; SĐT ghi vào ``phones`` để fixture dọn sau test.

    Mã HV cấp như màn Hội viên (khóa advisory + ``next_code``) để không làm lệch mã kế tiếp.
    """
    code = None
    if member:
        await s.execute(text("SELECT pg_advisory_xact_lock(hashtext('member_code'))"))
        code = await next_member_code(s)
    phone = unique_phone()
    phones.append(phone)
    s.add(
        Customer(
            kind="member" if member else "temp",
            member_code=code,
            full_name="Hội viên báo cáo",
            phone=phone,
            created_at=created_at,
        )
    )
    await s.flush()
