from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.modules.booking_engine.models import DEFAULT_TENANT_SETTINGS, Tenant


def current_tenant_id() -> int:
    return settings.TENANT_ID


async def get_tenant(session: AsyncSession, tenant_id: int, for_update: bool = False) -> Tenant:
    stmt = select(Tenant).where(Tenant.id == tenant_id)
    if for_update:
        stmt = stmt.with_for_update()
    tenant = await session.scalar(stmt)
    if tenant is None:
        # Lỗi cấu hình bản chạy (TENANT_ID không có trong DB) – không phải lỗi người dùng
        raise RuntimeError(f"Booking tenant {tenant_id} does not exist")
    return tenant


def tenant_settings(tenant: Tenant) -> dict[str, Any]:
    return {**DEFAULT_TENANT_SETTINGS, **(tenant.settings or {})}


def tz_of(tenant: Tenant) -> ZoneInfo:
    return ZoneInfo(tenant.timezone)


def today_of(tenant: Tenant) -> date:
    return datetime.now(tz_of(tenant)).date()


def resource_label(tenant: Tenant) -> str:
    return str(tenant_settings(tenant)["resource_label"])
