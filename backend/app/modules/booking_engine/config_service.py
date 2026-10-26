"""Cấu hình tài nguyên, giờ hoạt động, ngày đặc biệt, bảng giá, báo giá (T-005 mục D).

Hàm ở đây **không commit** – lớp gọi (router qua idempotency, script seed, BFF) sở hữu transaction.
"""

from datetime import date, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.errors import AppError
from app.modules.booking_engine import occupancy, outbox
from app.modules.booking_engine.dto import (
    Actor,
    PriceCellOut,
    PriceTable,
    PriceTableUpdate,
    QuoteIn,
    QuoteItem,
    QuoteOut,
    ResourceCreate,
    ResourceList,
    ResourceOut,
    ResourceTypeOut,
    ResourceUpdate,
    SpecialDayIn,
    SpecialDayOut,
)
from app.modules.booking_engine.models import (
    BANDS,
    DAY_TYPES,
    PriceRule,
    Resource,
    ResourceSchedule,
    ResourceType,
    SpecialDay,
)
from app.modules.booking_engine.pricing import (
    BAND_LABELS,
    day_type_of,
    slot_price,
    special_day_on,
)
from app.modules.booking_engine.schedules import (
    Hours,
    effective_on,
    pending_after,
    schedule_out,
    schedules_of,
    to_hhmm,
    validate_hours,
)
from app.modules.booking_engine.tenant import (
    get_tenant,
    resource_label,
    tenant_settings,
    today_of,
    tz_of,
)

NAME_MAX = 50
PRICE_MAX = 100_000_000
EXCLUSION_VIOLATION = "23P01"
UNIQUE_VIOLATION = "23505"
STALE_MESSAGE = "Dữ liệu vừa được thay đổi ở máy khác. Tải lại để xem bản mới nhất."


def _audit_actor(actor: Actor) -> AuditActor:
    return AuditActor(type=actor.type, id=actor.id, label=actor.label)


def _sqlstate(e: IntegrityError) -> str | None:
    return getattr(e.orig, "sqlstate", None)


def _not_found(what: str) -> AppError:
    return AppError("E-NOT-FOUND", f"Không tìm thấy {what}.", 404)


# ---------------------------------------------------------------- loại tài nguyên


async def _types(session: AsyncSession, tenant_id: int) -> list[ResourceType]:
    stmt = (
        select(ResourceType)
        .where(ResourceType.tenant_id == tenant_id)
        .order_by(ResourceType.sort, ResourceType.code)
    )
    return list((await session.scalars(stmt)).all())


async def _type_by_code(session: AsyncSession, tenant_id: int, code: str) -> ResourceType:
    row = await session.scalar(
        select(ResourceType).where(ResourceType.tenant_id == tenant_id, ResourceType.code == code)
    )
    if row is None:
        raise AppError("E-CFG-9", "Loại không hợp lệ.", 422)
    return row


async def upsert_resource_type(
    session: AsyncSession, tenant_id: int, code: str, name: str, sort: int = 0
) -> None:
    stmt = insert(ResourceType).values(tenant_id=tenant_id, code=code, name=name, sort=sort)
    stmt = stmt.on_conflict_do_update(
        index_elements=[ResourceType.tenant_id, ResourceType.code],
        set_={"name": stmt.excluded.name, "sort": stmt.excluded.sort},
    )
    await session.execute(stmt)


# ---------------------------------------------------------------- tài nguyên


async def _resource_by_code(
    session: AsyncSession, tenant_id: int, code: str, for_update: bool = False
) -> Resource:
    stmt = select(Resource).where(Resource.tenant_id == tenant_id, Resource.code == code.upper())
    if for_update:
        stmt = stmt.with_for_update()
    row = await session.scalar(stmt)
    if row is None:
        raise _not_found(code)
    return row


def _clean_name(name: str, label: str) -> str:
    name = " ".join(name.split())
    if not name:
        raise AppError("E-CFG-1", f"Vui lòng nhập Tên {label}.", 422)
    if len(name) > NAME_MAX:
        raise AppError("E-CFG-1", f"Tên {label} tối đa {NAME_MAX} ký tự.", 422)
    return name


def _duplicate_name(label: str) -> AppError:
    return AppError("E-CFG-1", f"Tên {label} đã có. Vui lòng đặt tên khác.", 409)


async def _ensure_unique_name(
    session: AsyncSession, tenant_id: int, name: str, label: str, exclude_id: int | None = None
) -> None:
    stmt = select(Resource.id).where(
        Resource.tenant_id == tenant_id, func.lower(Resource.name) == name.lower()
    )
    if exclude_id is not None:
        stmt = stmt.where(Resource.id != exclude_id)
    if await session.scalar(stmt.limit(1)) is not None:
        raise _duplicate_name(label)


def _resource_out(
    r: Resource, rtype: ResourceType, versions: list[ResourceSchedule], today: date
) -> ResourceOut:
    return ResourceOut(
        code=r.code,
        name=r.name,
        resource_type_code=rtype.code,
        resource_type_name=rtype.name,
        sort_order=r.sort_order,
        is_active=r.is_active,
        version=r.version,
        schedule=schedule_out(effective_on(versions, today)),
        pending_schedule=schedule_out(pending_after(versions, today)),
    )


async def list_resources(session: AsyncSession, tenant_id: int) -> ResourceList:
    tenant = await get_tenant(session, tenant_id)
    today = today_of(tenant)
    types = await _types(session, tenant_id)
    by_id = {t.id: t for t in types}
    rows = (
        await session.scalars(
            select(Resource)
            .where(Resource.tenant_id == tenant_id)
            .order_by(Resource.sort_order, Resource.code)
        )
    ).all()
    schedules = await schedules_of(session, tenant_id)
    return ResourceList(
        items=[
            _resource_out(r, by_id[r.resource_type_id], schedules.get(r.id, []), today)
            for r in rows
        ],
        resource_types=[ResourceTypeOut(code=t.code, name=t.name) for t in types],
    )


async def _resource_view(session: AsyncSession, tenant_id: int, r: Resource) -> ResourceOut:
    tenant = await get_tenant(session, tenant_id)
    rtype = await session.get(ResourceType, r.resource_type_id)
    versions = (await schedules_of(session, tenant_id, [r.id])).get(r.id, [])
    return _resource_out(r, rtype, versions, today_of(tenant))


async def create_resource(
    session: AsyncSession, tenant_id: int, actor: Actor, data: ResourceCreate
) -> ResourceOut:
    # Khóa dòng tenant: cấp mã / thứ tự tuần tự, không trùng khi 2 máy cùng thêm
    tenant = await get_tenant(session, tenant_id, for_update=True)
    label = resource_label(tenant)
    name = _clean_name(data.name, label)
    rtype = await _type_by_code(session, tenant_id, data.resource_type_code)
    hours = validate_hours(data.open_time, data.close_time, data.peak_bands)
    await _ensure_unique_name(session, tenant_id, name, label)

    prefix = str(tenant_settings(tenant)["resource_code_prefix"])
    codes = await session.scalars(
        select(Resource.code).where(
            Resource.tenant_id == tenant_id, Resource.code.startswith(prefix)
        )
    )
    numbers = [int(c[len(prefix) :]) for c in codes if c[len(prefix) :].isdigit()]
    code = f"{prefix}{max(numbers, default=0) + 1:02d}"
    sort_order = (
        await session.scalar(
            select(func.max(Resource.sort_order)).where(Resource.tenant_id == tenant_id)
        )
        or 0
    ) + 1

    resource = Resource(
        tenant_id=tenant_id,
        code=code,
        name=name,
        resource_type_id=rtype.id,
        sort_order=sort_order,
        is_active=True,
        attributes={},
        version=1,
    )
    try:
        async with session.begin_nested():
            session.add(resource)
            await session.flush()
    except IntegrityError as e:
        if _sqlstate(e) == UNIQUE_VIOLATION:
            raise _duplicate_name(label) from None
        raise
    today = today_of(tenant)
    session.add(
        ResourceSchedule(
            tenant_id=tenant_id,
            resource_id=resource.id,
            effective_from=today,
            open_minute=hours.open_minute,
            close_minute=hours.close_minute,
            peak_bands=hours.peak_bands_hhmm,
            created_by_label=actor.label,
        )
    )
    detail = {
        "name": name,
        "resource_type": rtype.code,
        "open_time": to_hhmm(hours.open_minute),
        "close_time": to_hhmm(hours.close_minute),
        "peak_bands": hours.peak_bands_hhmm,
    }
    audit(session, _audit_actor(actor), "config.resource.create", "resource", code, detail)
    outbox.add_event(session, tenant_id, "config.resource.created", {"code": code})
    await session.flush()
    return await _resource_view(session, tenant_id, resource)


async def update_resource(
    session: AsyncSession, tenant_id: int, actor: Actor, code: str, data: ResourceUpdate
) -> ResourceOut:
    tenant = await get_tenant(session, tenant_id)
    label = resource_label(tenant)
    r = await _resource_by_code(session, tenant_id, code, for_update=True)
    if data.version != r.version:
        raise AppError("E-CFG-7", STALE_MESSAGE, 409)
    today = today_of(tenant)
    tomorrow = today + timedelta(days=1)
    tz = tz_of(tenant)
    changes: dict = {}

    if data.name is not None:
        name = _clean_name(data.name, label)
        if name != r.name:
            await _ensure_unique_name(session, tenant_id, name, label, exclude_id=r.id)
            changes["name"] = {"from": r.name, "to": name}
            r.name = name

    if data.resource_type_code is not None:
        rtype = await _type_by_code(session, tenant_id, data.resource_type_code)
        if rtype.id != r.resource_type_id:
            old = await session.get(ResourceType, r.resource_type_id)
            changes["resource_type"] = {"from": old.code, "to": rtype.code}
            r.resource_type_id = rtype.id

    if data.is_active is not None and data.is_active != r.is_active:
        if not data.is_active:
            busy = await occupancy.occupied_from(session, tenant_id, r.id, today, tz)
            if busy:
                raise AppError(
                    "E-CFG-4",
                    f"{label.capitalize()} còn {len(busy)} lịch đặt từ hôm nay. "
                    f"Chuyển các lịch này sang {label} khác trước khi ngừng {label}.",
                    409,
                    **occupancy.listing(busy),
                )
        changes["is_active"] = {"from": r.is_active, "to": data.is_active}
        r.is_active = data.is_active

    if any(v is not None for v in (data.open_time, data.close_time, data.peak_bands)):
        versions = (await schedules_of(session, tenant_id, [r.id])).get(r.id, [])
        current = effective_on(versions, today)
        latest = pending_after(versions, today) or current
        if latest is None:
            raise RuntimeError(f"Resource {r.code} has no schedule")
        base = Hours.of(latest)
        hours = validate_hours(
            data.open_time or to_hhmm(base.open_minute),
            data.close_time or to_hhmm(base.close_minute),
            data.peak_bands if data.peak_bands is not None else latest.peak_bands,
        )
        if hours != base:
            outside = await occupancy.occupied_from(
                session,
                tenant_id,
                r.id,
                tomorrow,
                tz,
                outside=(hours.open_minute, hours.close_minute),
            )
            if outside:
                raise AppError(
                    "E-CFG-3",
                    f"Chưa đổi được giờ: còn {len(outside)} khung đã có người dùng "
                    "nằm ngoài giờ mới. "
                    f"Xử lý các khung này ở màn Đặt {label} rồi lưu lại.",
                    409,
                    **occupancy.listing(outside),
                )
            # Áp dụng từ ngày mai: ghi đè bản của ngày mai; quay về đúng lịch hiện tại = bỏ bản chờ
            await session.execute(
                delete(ResourceSchedule).where(
                    ResourceSchedule.resource_id == r.id,
                    ResourceSchedule.effective_from >= tomorrow,
                )
            )
            if current is None or Hours.of(current) != hours:
                session.add(
                    ResourceSchedule(
                        tenant_id=tenant_id,
                        resource_id=r.id,
                        effective_from=tomorrow,
                        open_minute=hours.open_minute,
                        close_minute=hours.close_minute,
                        peak_bands=hours.peak_bands_hhmm,
                        created_by_label=actor.label,
                    )
                )
            changes["schedule"] = {
                "effective_from": tomorrow.isoformat(),
                "open_time": to_hhmm(hours.open_minute),
                "close_time": to_hhmm(hours.close_minute),
                "peak_bands": hours.peak_bands_hhmm,
            }

    if changes:
        r.version += 1
        r.updated_at = func.now()
        try:
            async with session.begin_nested():
                await session.flush()
        except IntegrityError as e:
            if _sqlstate(e) == UNIQUE_VIOLATION:
                raise _duplicate_name(label) from None
            raise
        audit(session, _audit_actor(actor), "config.resource.update", "resource", r.code, changes)
        outbox.add_event(
            session, tenant_id, "config.resource.updated", {"code": r.code, "fields": list(changes)}
        )
        await session.flush()
        await session.refresh(r)
    return await _resource_view(session, tenant_id, r)


# ---------------------------------------------------------------- bảng giá


async def get_price_table(session: AsyncSession, tenant_id: int) -> PriceTable:
    tenant = await get_tenant(session, tenant_id)
    types = await _types(session, tenant_id)
    by_id = {t.id: t for t in types}
    rows = (await session.scalars(select(PriceRule).where(PriceRule.tenant_id == tenant_id))).all()
    order = {
        (t.id, d, b): i
        for i, (t, d, b) in enumerate((t, d, b) for t in types for d in DAY_TYPES for b in BANDS)
    }
    rows = sorted(rows, key=lambda p: order.get((p.resource_type_id, p.day_type, p.band), 1 << 30))
    return PriceTable(
        version=tenant.version,
        updated_at=tenant.prices_updated_at,
        updated_by=tenant.prices_updated_by,
        resource_types=[ResourceTypeOut(code=t.code, name=t.name) for t in types],
        prices=[
            PriceCellOut(
                resource_type_code=by_id[p.resource_type_id].code,
                day_type=p.day_type,
                band=p.band,
                price_per_hour=p.price_per_hour,
            )
            for p in rows
        ],
    )


def _invalid_price(message: str = "Giá phải là số nguyên lớn hơn 0.") -> AppError:
    return AppError("E-CFG-6", message, 422)


async def update_price_table(
    session: AsyncSession, tenant_id: int, actor: Actor, data: PriceTableUpdate
) -> PriceTable:
    tenant = await get_tenant(session, tenant_id, for_update=True)
    if data.version != tenant.version:
        raise AppError("E-CFG-7", STALE_MESSAGE, 409)
    types = {t.code: t for t in await _types(session, tenant_id)}
    cells: dict[tuple[str, str, str], int] = {}
    for cell in data.prices:
        if cell.resource_type_code not in types:
            raise AppError("E-CFG-9", "Loại không hợp lệ.", 422)
        key = (cell.resource_type_code, cell.day_type, cell.band)
        if key in cells:
            raise _invalid_price("Mỗi ô giá chỉ được gửi một lần.")
        if not 0 < cell.price_per_hour <= PRICE_MAX:
            raise _invalid_price()
        cells[key] = cell.price_per_hour
    expected = {(t, d, b) for t in types for d in DAY_TYPES for b in BANDS}
    if set(cells) != expected:
        raise _invalid_price("Vui lòng nhập đủ giá cho mọi ô của bảng giá.")

    existing = {
        (p.resource_type_id, p.day_type, p.band): p.price_per_hour
        for p in await session.scalars(select(PriceRule).where(PriceRule.tenant_id == tenant_id))
    }
    changes = []
    for (type_code, day_type, band), price in sorted(cells.items()):
        type_id = types[type_code].id
        old = existing.get((type_id, day_type, band))
        if old == price:
            continue
        changes.append(
            {
                "resource_type": type_code,
                "day_type": day_type,
                "band": band,
                "from": old,
                "to": price,
            }
        )
        stmt = insert(PriceRule).values(
            tenant_id=tenant_id,
            resource_type_id=type_id,
            day_type=day_type,
            band=band,
            price_per_hour=price,
        )
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    PriceRule.tenant_id,
                    PriceRule.resource_type_id,
                    PriceRule.day_type,
                    PriceRule.band,
                ],
                set_={"price_per_hour": stmt.excluded.price_per_hour},
            )
        )
    tenant.version += 1
    tenant.prices_updated_at = func.now()
    tenant.prices_updated_by = actor.label
    audit(
        session,
        _audit_actor(actor),
        "config.price.update",
        "price_table",
        f"v{tenant.version}",
        {"version": tenant.version, "changes": changes},
    )
    outbox.add_event(session, tenant_id, "config.price.updated", {"version": tenant.version})
    await session.flush()
    await session.refresh(tenant)
    return await get_price_table(session, tenant_id)


# ---------------------------------------------------------------- ngày Lễ / Tết


def _special_out(row: SpecialDay) -> SpecialDayOut:
    return SpecialDayOut(
        id=row.id,
        date_from=row.date_from,
        date_to=row.date_to,
        name=row.name,
        day_type="holiday",
    )


async def list_special_days(
    session: AsyncSession, tenant_id: int, year: int | None = None
) -> list[SpecialDayOut]:
    stmt = select(SpecialDay).where(SpecialDay.tenant_id == tenant_id)
    if year is not None:
        stmt = stmt.where(
            SpecialDay.date_from >= date(year, 1, 1), SpecialDay.date_from <= date(year, 12, 31)
        )
    rows = await session.scalars(stmt.order_by(SpecialDay.date_from))
    return [_special_out(r) for r in rows]


async def create_special_day(
    session: AsyncSession, tenant_id: int, actor: Actor, data: SpecialDayIn
) -> SpecialDayOut:
    date_from = data.date_from
    date_to = data.date_to or data.date_from
    clash = await session.scalar(
        select(SpecialDay)
        .where(
            SpecialDay.tenant_id == tenant_id,
            SpecialDay.date_from <= date_to,
            SpecialDay.date_to >= date_from,
        )
        .order_by(SpecialDay.date_from)
        .limit(1)
    )
    if clash is not None:
        day = max(date_from, clash.date_from)
        raise AppError("E-CFG-8", f"Ngày {day:%d/%m} đã nằm trong {clash.name}.", 409)
    row = SpecialDay(tenant_id=tenant_id, date_from=date_from, date_to=date_to, name=data.name)
    try:
        async with session.begin_nested():
            session.add(row)
            await session.flush()
    except IntegrityError as e:
        if _sqlstate(e) == EXCLUSION_VIOLATION:
            raise AppError(
                "E-CFG-8", "Khoảng ngày vừa được thêm vào một ngày Lễ/Tết khác.", 409
            ) from None
        raise
    audit(
        session,
        _audit_actor(actor),
        "config.special_day.create",
        "special_day",
        str(row.id),
        {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(), "name": row.name},
    )
    outbox.add_event(
        session,
        tenant_id,
        "config.special_day.created",
        {"id": row.id, "date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
    )
    await session.flush()
    return _special_out(row)


async def delete_special_day(
    session: AsyncSession, tenant_id: int, actor: Actor, special_day_id: int
) -> None:
    row = await session.scalar(
        select(SpecialDay)
        .where(SpecialDay.tenant_id == tenant_id, SpecialDay.id == special_day_id)
        .with_for_update()
    )
    if row is None:
        raise _not_found("ngày Lễ/Tết")
    detail = {
        "date_from": row.date_from.isoformat(),
        "date_to": row.date_to.isoformat(),
        "name": row.name,
    }
    await session.delete(row)
    audit(
        session,
        _audit_actor(actor),
        "config.special_day.delete",
        "special_day",
        str(special_day_id),
        detail,
    )
    outbox.add_event(
        session, tenant_id, "config.special_day.deleted", {"id": special_day_id, **detail}
    )
    await session.flush()


# ---------------------------------------------------------------- báo giá


def _not_sold(message: str) -> AppError:
    return AppError("E-CFG-10", message, 422)


async def quote(session: AsyncSession, tenant_id: int, data: QuoteIn) -> QuoteOut:
    tenant = await get_tenant(session, tenant_id)
    label = resource_label(tenant)
    if data.start_hour >= data.end_hour:
        raise _not_sold("Giờ kết thúc phải sau giờ bắt đầu.")
    r = await _resource_by_code(session, tenant_id, data.resource_code)
    versions = (await schedules_of(session, tenant_id, [r.id])).get(r.id, [])
    sched = effective_on(versions, data.date)
    if not r.is_active or sched is None:
        raise _not_sold(f"{r.name} không nhận đặt vào ngày {data.date:%d/%m/%Y}.")
    hours = Hours.of(sched)
    for h in range(data.start_hour, data.end_hour):
        if not hours.sells(h * 60, h * 60 + 60):
            raise _not_sold(f"Khung {h:02d}:00–{h + 1:02d}:00 của {r.name} không bán.")

    special = await special_day_on(session, tenant_id, data.date)
    day_type = day_type_of(data.date, special is not None)
    prices = {
        p.band: p.price_per_hour
        for p in await session.scalars(
            select(PriceRule).where(
                PriceRule.tenant_id == tenant_id,
                PriceRule.resource_type_id == r.resource_type_id,
                PriceRule.day_type == day_type,
            )
        )
    }
    items: list[QuoteItem] = []
    for h in range(data.start_hour, data.end_hour):
        needed = {"peak" if hours.is_peak(m) else "offpeak" for m in (h * 60, h * 60 + 30)}
        if not needed <= prices.keys():
            raise AppError(
                "E-019",
                f"Chưa có giá cho {label} này vào ngày {data.date:%d/%m/%Y}. "
                "Vui lòng cập nhật Bảng giá.",
                422,
            )
        band, price = slot_price(hours, h * 60, prices)
        items.append(
            QuoteItem(
                start_time=f"{h:02d}:00",
                end_time=f"{h + 1:02d}:00",
                band=band,
                label=BAND_LABELS[band],
                price=price,
            )
        )
    return QuoteOut(
        resource_code=r.code,
        resource_name=r.name,
        date=data.date,
        day_type=day_type,
        price_version=tenant.version,
        items=items,
        total_amount=sum(i.price for i in items),
    )
