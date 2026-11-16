"""T-006 §8: bảng giá công khai từ engine + luồng đặt sân cũ đã gỡ."""

from sqlalchemy import text

from app.core.db import engine
from tests.conftest import API
from tests.helpers_booking import BK, today

PUBLIC = f"{BK}/prices/public"


async def test_public_prices_shape(anon, admin):
    r = await anon.get(PUBLIC)
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "public, max-age=300"
    data = r.json()
    assert set(data) == {
        "currency",
        "unit",
        "updated_at",
        "resource_types",
        "prices",
        "opening_hours",
        "peak_bands",
        "special_days",
    }
    assert (data["currency"], data["unit"]) == ("VND", "hour")
    types = {t["code"]: t for t in data["resource_types"]}
    # Seed: 4 sân thường + S05 VIP hoạt động (S06 VIP ngừng); test khác có thể thêm sân
    assert types["vip"]["resource_count"] >= 1 and types["thuong"]["resource_count"] >= 4
    cells = {(p["resource_type_code"], p["day_type"], p["band"]) for p in data["prices"]}
    assert len(cells) == 12
    assert data["opening_hours"]["earliest_open"] <= "05:00"
    peaks = {p["resource_type_code"]: p["bands"] for p in data["peak_bands"]}
    assert ["17:00", "21:00"] in peaks["vip"]
    for day in data["special_days"]:
        assert day["date_to"] >= today().isoformat()
    for word in ("version", "updated_by", '"id"'):
        assert word not in r.text


async def test_legacy_booking_api_removed(anon, admin):
    for path in ("/courts", "/venue/config", "/price-rules", "/bookings/availability"):
        assert (await anon.get(f"{API}{path}")).status_code == 404, path
    assert (await admin.get(f"{API}/admin/bookings")).status_code == 404


async def test_legacy_tables_renamed_not_dropped():
    async with engine.connect() as conn:
        names = set(
            await conn.scalars(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name LIKE 'legacy_%'"
                )
            )
        )
    assert names == {
        "legacy_courts",
        "legacy_price_rules",
        "legacy_bookings",
        "legacy_booking_slots",
        "legacy_payments",
    }
