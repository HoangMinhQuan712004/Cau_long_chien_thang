from fastapi import APIRouter, status

from app.core.config import settings
from app.core.errors import NotFound
from app.modules.auth.deps import AdminUser, SessionDep
from app.modules.courts import service
from app.modules.courts.models import PriceRule
from app.modules.courts.schemas import (
    CourtIn,
    CourtOut,
    PriceRuleIn,
    PriceRuleOut,
    VenueConfigOut,
)

router = APIRouter(tags=["courts"])


@router.get("/venue/config", response_model=VenueConfigOut)
async def venue_config():
    return VenueConfigOut(
        open_time=settings.OPEN_TIME,
        close_time=settings.CLOSE_TIME,
        slot_minutes=settings.SLOT_MINUTES,
        min_booking_minutes=settings.MIN_BOOKING_MINUTES,
        max_advance_days=settings.MAX_ADVANCE_DAYS,
        hold_minutes=settings.HOLD_MINUTES,
        timezone=settings.TIMEZONE,
    )


@router.get("/courts", response_model=list[CourtOut])
async def list_courts(session: SessionDep):
    return await service.list_courts(session)


@router.get("/price-rules", response_model=list[PriceRuleOut])
async def list_price_rules(session: SessionDep):
    return await service.list_price_rules(session)


# --- Admin ---
admin_router = APIRouter(prefix="/admin", tags=["admin: courts"])


@admin_router.get("/courts", response_model=list[CourtOut])
async def admin_list_courts(_: AdminUser, session: SessionDep):
    return await service.list_courts(session, only_active=False)


@admin_router.post("/courts", response_model=CourtOut, status_code=status.HTTP_201_CREATED)
async def create_court(data: CourtIn, _: AdminUser, session: SessionDep):
    return await service.save_court(session, data)


@admin_router.put("/courts/{court_id}", response_model=CourtOut)
async def update_court(court_id: int, data: CourtIn, _: AdminUser, session: SessionDep):
    court = await service.get_court(session, court_id)
    return await service.save_court(session, data, court)


@admin_router.get("/price-rules", response_model=list[PriceRuleOut])
async def admin_list_price_rules(_: AdminUser, session: SessionDep):
    return await service.list_price_rules(session, only_active=False)


@admin_router.post("/price-rules", response_model=PriceRuleOut, status_code=status.HTTP_201_CREATED)
async def create_price_rule(data: PriceRuleIn, _: AdminUser, session: SessionDep):
    return await service.save_price_rule(session, data)


@admin_router.put("/price-rules/{rule_id}", response_model=PriceRuleOut)
async def update_price_rule(rule_id: int, data: PriceRuleIn, _: AdminUser, session: SessionDep):
    rule = await session.get(PriceRule, rule_id)
    if not rule:
        raise NotFound("Không tìm thấy bảng giá")
    return await service.save_price_rule(session, data, rule)


@admin_router.delete("/price-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_price_rule(rule_id: int, _: AdminUser, session: SessionDep):
    rule = await session.get(PriceRule, rule_id)
    if not rule:
        raise NotFound("Không tìm thấy bảng giá")
    await session.delete(rule)
    await session.commit()
