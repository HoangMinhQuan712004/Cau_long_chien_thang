"""Đặt sân định kỳ (T-035 → T-043): một đơn gồm nhiều buổi, mỗi buổi = một booking nhiều giờ.

- Buổi sinh từ các thứ + khung giờ, từ ngày -> đến ngày trên một sân (T-035), **hoặc** do lớp gọi
  gửi tường minh (``sessions``, T-043): mỗi buổi một sân / giờ riêng, bỏ buổi = không gửi.
- Kiểm **theo từng ngày** với cấu hình có hiệu lực ngày đó: sân hoạt động, giờ mở cửa, bảng giá
  (thường / cuối tuần / Lễ × cao / thấp điểm – ``price_slots``), giờ đã qua, chỗ đã bị chiếm.
- Buổi trùng (``booked`` / ``event`` / ``hold``) có tối đa 2 gợi ý: cùng sân lệch giờ gần nhất,
  cùng giờ sân khác (ưu tiên cùng loại sân) – đều đã kiểm giờ mở cửa, giá, chỗ trống.
- Giảm % cho cả đơn: ``discount = round_half_up(gốc × pct / 100)``, phân bổ ``floor`` theo tỉ lệ
  giá, phần dư dồn buổi cuối -> tổng các buổi = gốc − giảm, khớp từng đồng.
- Tạo: một transaction, **tất cả hoặc không** – exclusion constraint vẫn là chốt chặn cuối.

Hàm ở đây **không commit**.
"""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit, audit_detail
from app.core.errors import AppError
from app.modules.booking_engine.audit_fields import customer_text_masked, new_values, vnd
from app.modules.booking_engine.booking_service import booking_item
from app.modules.booking_engine.codes import next_code
from app.modules.booking_engine.common import (
    EXCLUSION_VIOLATION,
    Ctx,
    audit_actor,
    context,
    sqlstate,
)
from app.modules.booking_engine.config_service import _resource_by_code, price_slots
from app.modules.booking_engine.dto import (
    Actor,
    CustomerSnapshot,
    RecurringCreated,
    RecurringIn,
    RecurringPreview,
    RecurringReason,
    RecurringSession,
    RecurringSuggestion,
)
from app.modules.booking_engine.holds import expire_holds, hold_visible
from app.modules.booking_engine.models import Allocation, Booking, Hold, Resource
from app.modules.booking_engine.orders import child_code, emit_created, new_order, snapshot_values
from app.modules.booking_engine.schedules import Hours, effective_on, schedules_of, to_hhmm

MAX_DAYS = 92
MAX_SESSIONS = 60
MAX_SUGGESTIONS = 2
REASONS: dict[RecurringReason, str] = {
    "booked": "Đã có người đặt",
    "event": "Có sự kiện",
    "hold": "Đang giữ chỗ online",
    "closed": "Ngoài giờ mở cửa",
    "inactive": "Sân ngừng hoạt động",
    "past": "Giờ đã qua",
    "no_price": "Chưa có bảng giá cho ngày này",
}
SUGGESTIBLE = {"booked", "event", "hold"}


def _invalid(message: str) -> AppError:
    return AppError("E-001", message, 422)


@dataclass(frozen=True)
class _Target:
    day: date
    resource: Resource
    a: int  # giờ bắt đầu
    b: int  # giờ kết thúc


@dataclass
class _Check:
    reason: RecurringReason | None
    price: int | None
    items: list


def _dates(ctx: Ctx, data: RecurringIn) -> list[date]:
    """Ngày khớp thứ trong [từ, đến]; kiểm giới hạn (422)."""
    weekdays = set(data.weekdays)
    if not weekdays:
        raise _invalid("Chọn ít nhất 1 thứ trong tuần.")
    if not weekdays <= set(range(1, 8)):
        raise _invalid("Thứ trong tuần phải từ 1 (Thứ 2) đến 7 (Chủ nhật).")
    if data.start_hour >= data.end_hour:
        raise _invalid("Giờ kết thúc phải sau giờ bắt đầu.")
    if data.date_from < ctx.today:
        raise AppError("E-004", "Từ ngày phải từ hôm nay trở đi.", 422)
    if data.date_to < data.date_from:
        raise AppError("E-016", "Từ ngày không được sau Đến ngày.", 422)
    if (data.date_to - data.date_from).days + 1 > MAX_DAYS:
        raise _invalid(f"Khoảng ngày tối đa {MAX_DAYS} ngày.")
    days = [
        d
        for i in range((data.date_to - data.date_from).days + 1)
        if (d := data.date_from + timedelta(days=i)).isoweekday() in weekdays
    ]
    if not days:
        raise _invalid("Không có buổi nào trong khoảng ngày đã chọn.")
    if len(days) > MAX_SESSIONS:
        raise _invalid(f"Mỗi đơn định kỳ tối đa {MAX_SESSIONS} buổi (đang có {len(days)}).")
    return days


async def _targets(session: AsyncSession, ctx: Ctx, data: RecurringIn) -> list[_Target]:
    """Các buổi cần kiểm, theo thời gian. ``sessions`` tường minh hoặc sinh từ lịch chung."""
    tid = ctx.tenant.id
    if data.sessions is None:
        r = await _resource_by_code(session, tid, data.resource_code)
        return [_Target(d, r, data.start_hour, data.end_hour) for d in _dates(ctx, data)]
    if not data.sessions:
        raise _invalid("Chọn ít nhất 1 buổi.")
    if len(data.sessions) > MAX_SESSIONS:
        raise _invalid(
            f"Mỗi đơn định kỳ tối đa {MAX_SESSIONS} buổi (đang có {len(data.sessions)})."
        )
    days = [s.date for s in data.sessions]
    if min(days) < ctx.today:
        raise AppError("E-004", "Không đặt được buổi của ngày đã qua.", 422)
    if (max(days) - min(days)).days + 1 > MAX_DAYS:
        raise _invalid(f"Các buổi phải nằm trong {MAX_DAYS} ngày.")
    resources: dict[str, Resource] = {}
    targets: list[_Target] = []
    for s in data.sessions:
        if s.start_hour >= s.end_hour:
            raise _invalid(f"Buổi {s.date:%d/%m}: giờ kết thúc phải sau giờ bắt đầu.")
        code = s.resource_code.strip().upper()
        if code not in resources:
            resources[code] = await _resource_by_code(session, tid, code)
        targets.append(_Target(s.date, resources[code], s.start_hour, s.end_hour))
    by_court: dict[tuple[date, int], list[_Target]] = defaultdict(list)
    for t in targets:
        by_court[(t.day, t.resource.id)].append(t)
    for group in by_court.values():  # cùng ngày, cùng sân: không được chồng giờ nhau
        group.sort(key=lambda t: t.a)
        for x, y in zip(group, group[1:], strict=False):
            if y.a < x.b:
                raise _invalid(f"Buổi {x.day:%d/%m} ở {x.resource.name} bị trùng giờ với nhau.")
    targets.sort(key=lambda t: (t.day, t.a, t.resource.sort_order, t.resource.code))
    return targets


class _World:
    """Dữ liệu của một lần kiểm: lịch mọi sân, chỗ chiếm từng ngày, giá – nạp một lần, dùng cho
    cả kiểm buổi lẫn tìm gợi ý (không lặp truy vấn cho từng ứng viên)."""

    def __init__(self, session: AsyncSession, ctx: Ctx):
        self.session, self.ctx = session, ctx
        self.resources: list[Resource] = []
        self.schedules: dict[int, list] = {}
        self._busy: dict[date, list[tuple[int, datetime, datetime, str]]] = {}
        self._prices: dict[tuple[int, date, int, int], tuple[int | None, list, str | None]] = {}

    async def load(self) -> "_World":
        self.resources = list(
            await self.session.scalars(
                select(Resource)
                .where(Resource.tenant_id == self.ctx.tenant.id, Resource.is_active.is_(True))
                .order_by(Resource.sort_order, Resource.code)
            )
        )
        self.schedules = await schedules_of(self.session, self.ctx.tenant.id)
        return self

    async def busy(self, day: date) -> list[tuple[int, datetime, datetime, str]]:
        """Chỗ đang chiếm trong ngày: (sân, bắt đầu, kết thúc, loại); giữ chỗ hết hạn bỏ qua."""
        if day not in self._busy:
            lo, hi = self.ctx.at(day, 0), self.ctx.at(day, 24 * 60)
            rows = await self.session.execute(
                select(Allocation.resource_id, Allocation.time_range, Allocation.kind, Hold.id)
                .outerjoin(Hold, (Hold.id == Allocation.hold_id) & hold_visible(self.ctx.now))
                .where(
                    Allocation.tenant_id == self.ctx.tenant.id,
                    Allocation.active.is_(True),
                    Allocation.time_range.overlaps(Range(lo, hi, bounds="[)")),
                )
            )
            self._busy[day] = [
                (rid, tr.lower, tr.upper, kind)
                for rid, tr, kind, hold_id in rows
                if kind != "hold" or hold_id is not None
            ]
        return self._busy[day]

    async def taken(self, r: Resource, start: datetime, end: datetime) -> RecurringReason | None:
        """Sự kiện > đã đặt > giữ chỗ online còn hiệu lực."""
        kinds = {
            kind
            for rid, lo, hi, kind in await self.busy(start.astimezone(self.ctx.tz).date())
            if rid == r.id and lo < end and start < hi
        }
        for kind, reason in (("session", "event"), ("booking", "booked"), ("hold", "hold")):
            if kind in kinds:
                return reason  # type: ignore[return-value]
        return None

    async def price(
        self, r: Resource, day: date, a: int, b: int
    ) -> tuple[int | None, list, str | None]:
        """(giá, bảng giá chi tiết, mã lỗi E-019 / E-CFG-10 nếu không định giá được)."""
        key = (r.id, day, a, b)
        if key not in self._prices:
            try:
                _, quote = await price_slots(self.session, self.ctx.tenant, r, day, a, b)
                self._prices[key] = (
                    sum(i.price for i in quote),
                    [i.model_dump() for i in quote],
                    None,
                )
            except AppError as e:
                self._prices[key] = (None, [], e.code)
        return self._prices[key]

    def sells(self, r: Resource, day: date, a: int, b: int) -> bool:
        sched = effective_on(self.schedules.get(r.id, []), day)
        return sched is not None and Hours.of(sched).sells(a * 60, b * 60)

    async def check(self, r: Resource, day: date, a: int, b: int) -> _Check:
        start = self.ctx.at(day, a * 60)
        if not r.is_active:
            return _Check("inactive", None, [])
        if not self.sells(r, day, a, b):
            return _Check("closed", None, [])
        price, items, error = await self.price(r, day, a, b)
        if price is None:
            return _Check("no_price" if error == "E-019" else "closed", None, [])
        if start <= self.ctx.now:
            return _Check("past", price, items)
        return _Check(await self.taken(r, start, self.ctx.at(day, b * 60)), price, items)

    async def suggestions(self, t: _Target) -> list[RecurringSuggestion]:
        """(1) cùng sân, lệch giờ gần nhất cùng độ dài; (2) cùng giờ, sân khác còn trống."""
        out: list[RecurringSuggestion] = []
        length = t.b - t.a
        shifts = sorted(
            (h for h in range(0, 25 - length) if h != t.a), key=lambda h: (abs(h - t.a), h)
        )
        for h in shifts:
            c = await self.check(t.resource, t.day, h, h + length)
            if c.reason is None and c.price is not None:
                out.append(self._suggestion("shift", t.resource, h, h + length, c.price))
                break
        others = sorted(
            (r for r in self.resources if r.id != t.resource.id),
            key=lambda r: (r.resource_type_id != t.resource.resource_type_id, r.sort_order, r.code),
        )
        for r in others:
            c = await self.check(r, t.day, t.a, t.b)
            if c.reason is None and c.price is not None:
                out.append(self._suggestion("court", r, t.a, t.b, c.price))
                break
        return out[:MAX_SUGGESTIONS]

    @staticmethod
    def _suggestion(kind: str, r: Resource, a: int, b: int, price: int) -> RecurringSuggestion:
        return RecurringSuggestion(
            kind=kind,  # type: ignore[arg-type]
            resource_code=r.code,
            resource_name=r.name,
            start_hour=a,
            end_hour=b,
            price=price,
        )


def _allocate(prices: list[int], pct: int) -> tuple[int, int, list[int]]:
    """(gốc, giảm, giảm từng buổi): half-up cho tổng giảm, floor theo tỉ lệ, dư dồn buổi cuối."""
    original = sum(prices)
    discount = (original * pct + 50) // 100
    if original == 0 or discount == 0:
        return original, 0, [0] * len(prices)
    shares = [p * discount // original for p in prices]
    shares[-1] += discount - sum(shares)
    return original, discount, shares


async def _plan(
    session: AsyncSession, ctx: Ctx, data: RecurringIn
) -> tuple[list[RecurringSession], list[list], list[_Target]]:
    """Từng buổi + lý do lỗi + giá + gợi ý; trả kèm bảng giá chi tiết và sân của từng buổi."""
    targets = await _targets(session, ctx, data)
    world = await _World(session, ctx).load()
    checks = [await world.check(t.resource, t.day, t.a, t.b) for t in targets]

    priced = [c.price for c in checks if c.price is not None]
    _, _, shares = _allocate(priced, data.discount_pct)
    share_of = iter(shares)
    out = []
    for t, c in zip(targets, checks, strict=True):
        after = c.price - next(share_of) if c.price is not None else None
        out.append(
            RecurringSession(
                date=t.day,
                weekday=t.day.isoweekday(),
                resource_code=t.resource.code,
                resource_name=t.resource.name,
                start_hour=t.a,
                end_hour=t.b,
                start_time=to_hhmm(t.a * 60),
                end_time=to_hhmm(t.b * 60),
                start_at=ctx.at(t.day, t.a * 60),
                end_at=ctx.at(t.day, t.b * 60),
                price=c.price,
                price_after_discount=after,
                ok=c.reason is None,
                reason=c.reason,
                reason_text=REASONS[c.reason] if c.reason else None,
                suggestions=await world.suggestions(t) if c.reason in SUGGESTIBLE else [],
            )
        )
    return out, [c.items for c in checks], targets


def _summary(sessions: list[RecurringSession], pct: int) -> RecurringPreview:
    original, discount, _ = _allocate([s.price for s in sessions if s.price is not None], pct)
    return RecurringPreview(
        sessions=sessions,
        count=len(sessions),
        original_amount=original,
        discount_pct=pct,
        discount_amount=discount,
        total=original - discount,
        conflicts_count=sum(not s.ok for s in sessions),
    )


async def preview(session: AsyncSession, tenant_id: int, data: RecurringIn) -> RecurringPreview:
    """Xem trước – không ghi gì."""
    ctx = await context(session, tenant_id)
    sessions, _, _ = await _plan(session, ctx, data)
    return _summary(sessions, data.discount_pct)


def _not_bookable(sessions: list[RecurringSession]) -> AppError:
    bad = [s for s in sessions if not s.ok]
    return AppError(
        "E-BOOK-5",
        f"Có {len(bad)} buổi không đặt được.",
        409,
        conflicts=[
            {
                "date": s.date.isoformat(),
                "start": s.start_time,
                "resource_code": s.resource_code,
                "reason": s.reason,
                "reason_text": s.reason_text,
                "suggestions": [g.model_dump() for g in s.suggestions],
            }
            for s in bad
        ],
    )


async def create(
    session: AsyncSession,
    tenant_id: int,
    actor: Actor,
    data: RecurringIn,
    customer: CustomerSnapshot,
) -> RecurringCreated:
    """Một đơn (mã theo ngày buổi đầu) + mọi buổi ``unpaid`` trong một transaction.

    Có buổi lỗi -> 409 ``E-BOOK-5`` kèm ``conflicts`` (có gợi ý), không tạo gì. Hai Admin đặt chồng
    cùng lúc: exclusion constraint chặn người sau -> rollback cả đơn, tính lại danh sách buổi lỗi.
    """
    ctx = await context(session, tenant_id)
    await expire_holds(session)
    sessions, breakdowns, targets = await _plan(session, ctx, data)
    if any(not s.ok for s in sessions):
        raise _not_bookable(sessions)
    summary = _summary(sessions, data.discount_pct)
    discounted = data.discount_pct > 0

    order_code = await next_code(session, tenant_id, ctx.code_prefix, sessions[0].date)
    order = new_order(
        tenant_id, order_code, sessions[0].date, "counter", snapshot_values(customer), actor.label
    )
    order.kind = "recurring"
    order.discount_pct = data.discount_pct
    order.discount_amount = summary.discount_amount
    created: list[Booking] = []
    try:
        async with session.begin_nested():
            session.add(order)
            await session.flush()
            rows = zip(sessions, breakdowns, targets, strict=True)
            for seq, (s, items, t) in enumerate(rows, start=1):
                code = child_code(order_code, seq)
                booking = Booking(
                    tenant_id=tenant_id,
                    order_id=order.id,
                    seq=seq,
                    code=code,
                    source="counter",
                    resource_id=t.resource.id,
                    play_date=s.date,
                    start_at=s.start_at,
                    end_at=s.end_at,
                    amount=s.price_after_discount or 0,
                    list_amount=s.price if discounted else None,
                    price_breakdown=items,
                    payment_status="unpaid",
                    created_by_type=actor.type,
                    created_by_id=actor.id,
                    created_by_label=actor.label,
                    version=1,
                    **snapshot_values(customer),
                )
                session.add(booking)
                await session.flush()
                session.add(
                    Allocation(
                        tenant_id=tenant_id,
                        resource_id=t.resource.id,
                        time_range=Range(s.start_at, s.end_at, bounds="[)"),
                        kind="booking",
                        booking_id=booking.id,
                        owner_code=code,
                        active=True,
                    )
                )
                await session.flush()
                created.append(booking)
    except IntegrityError as e:
        if sqlstate(e) == EXCLUSION_VIOLATION:
            again, _, _ = await _plan(session, ctx, data)
            raise _not_bookable(again) from None
        raise

    courts = list(dict.fromkeys(t.resource.name for t in targets))
    first, last = sessions[0], sessions[-1]
    schedule_text = f"{len(sessions)} buổi, {first.date:%d/%m/%Y}–{last.date:%d/%m/%Y}"
    hours = {(s.start_time, s.end_time) for s in sessions}
    if len(hours) == 1:
        schedule_text += f", {first.start_time}–{first.end_time}"
    audit(
        session,
        audit_actor(actor),
        "booking.recurring.create",
        "booking_order",
        order_code,
        audit_detail(
            order_code,
            customer.display_name,
            new_values(
                **{
                    "Sân": ", ".join(courts),
                    "Lịch": schedule_text,
                    "Khách": customer_text_masked(customer),  # spec T-035: không SĐT đầy đủ
                    "Giảm giá": f"{data.discount_pct}% ({vnd(summary.discount_amount)})"
                    if data.discount_pct
                    else None,
                    "Phải thu": vnd(summary.total),
                }
            ),
            order_code=order_code,
            resource=targets[0].resource.code,
            resources=list(dict.fromkeys(t.resource.code for t in targets)),
            weekdays=sorted({s.weekday for s in sessions}),
            sessions=len(sessions),
            original_amount=summary.original_amount,
            discount_pct=data.discount_pct,
            discount_amount=summary.discount_amount,
            total=summary.total,
            customer_kind=customer.kind,
            member_code=customer.member_code,
        ),
    )
    for booking in created:
        await emit_created(session, tenant_id, order, booking)  # mỗi buổi tự có phòng (T-017)
    await session.flush()
    items_out = []
    for booking in created:
        await session.refresh(booking)
        items_out.append(await booking_item(session, ctx, booking))
    return RecurringCreated(
        order_code=order_code,
        bookings=items_out,
        original_amount=summary.original_amount,
        discount_pct=data.discount_pct,
        discount_amount=summary.discount_amount,
        total=summary.total,
    )
