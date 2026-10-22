from datetime import datetime, timedelta

from slugify import slugify
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.errors import BadRequest, Conflict, NotFound
from app.modules.courts.models import Court, PriceRule
from app.modules.courts.schemas import CourtIn, PriceRuleIn


async def list_courts(session: AsyncSession, only_active: bool = True) -> list[Court]:
    stmt = select(Court).order_by(Court.sort_order, Court.id)
    if only_active:
        stmt = stmt.where(Court.is_active.is_(True))
    return list((await session.scalars(stmt)).all())


async def get_court(session: AsyncSession, court_id: int) -> Court:
    court = await session.get(Court, court_id)
    if not court:
        raise NotFound("Không tìm thấy sân")
    return court


async def get_active_courts_by_ids(session: AsyncSession, ids: set[int]) -> dict[int, Court]:
    courts = await session.scalars(
        select(Court).where(Court.id.in_(ids), Court.is_active.is_(True))
    )
    return {c.id: c for c in courts}


async def save_court(session: AsyncSession, data: CourtIn, court: Court | None = None) -> Court:
    values = data.model_dump()
    values["slug"] = slugify(data.slug or data.name)
    clash = await session.scalar(select(Court).where(Court.slug == values["slug"]))
    if clash and (court is None or clash.id != court.id):
        raise Conflict("Slug đã tồn tại")
    if court is None:
        court = Court(**values)
        session.add(court)
    else:
        for k, v in values.items():
            setattr(court, k, v)
    await session.commit()
    await session.refresh(court)
    return court


async def list_price_rules(session: AsyncSession, only_active: bool = True) -> list[PriceRule]:
    stmt = select(PriceRule).order_by(PriceRule.court_id.nulls_first(), PriceRule.start_time)
    if only_active:
        stmt = stmt.where(PriceRule.is_active.is_(True))
    return list((await session.scalars(stmt)).all())


async def save_price_rule(
    session: AsyncSession, data: PriceRuleIn, rule: PriceRule | None = None
) -> PriceRule:
    if data.court_id is not None:
        await get_court(session, data.court_id)
    if rule is None:
        rule = PriceRule(**data.model_dump())
        session.add(rule)
    else:
        for k, v in data.model_dump().items():
            setattr(rule, k, v)
    await session.commit()
    await session.refresh(rule)
    return rule


class PriceCalculator:
    """Tính giá một khoảng thời gian bằng cách chia thành các bước SLOT_MINUTES."""

    def __init__(self, rules: list[PriceRule]):
        self.rules = [r for r in rules if r.is_active]

    def _rule_for(self, court_id: int, local_start: datetime) -> PriceRule | None:
        dow, t = local_start.weekday(), local_start.time()
        candidates = [
            r
            for r in self.rules
            if (r.court_id is None or r.court_id == court_id)
            and dow in r.days_of_week
            and r.start_time <= t < r.end_time
        ]
        if not candidates:
            return None
        # Rule riêng của sân thắng rule chung, sau đó tới priority
        return max(candidates, key=lambda r: (r.court_id is not None, r.priority))

    def price(self, court_id: int, start: datetime, end: datetime) -> int:
        step = timedelta(minutes=settings.SLOT_MINUTES)
        cursor = start.astimezone(settings.tz)
        end = end.astimezone(settings.tz)
        total = 0
        while cursor < end:
            rule = self._rule_for(court_id, cursor)
            if rule is None:
                raise BadRequest(f"Chưa có bảng giá cho khung giờ {cursor:%H:%M %d/%m}")
            total += rule.price_per_hour * settings.SLOT_MINUTES // 60
            cursor += step
        return total
