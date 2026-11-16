"""Giờ giả cho cả bộ test (T-067): ``TEST_FAKE_NOW=2026-11-10T23:59:30+07:00 pytest -q``.

Kiểm test không phụ thuộc giờ chạy (ranh giờ / ngày VN, 19h, nửa đêm). Giờ chạy tiếp từ mốc đó
(``tick``) – qua ranh giữa chừng đúng là điều cần thử.

- Python: ``time-machine`` dời ``datetime.now`` / ``time.time`` (không dời ``time.monotonic``:
  ``asyncio`` / timeout vẫn theo đồng hồ thật).
- Postgres: hàm ``public.now()`` = ``pg_catalog.now()`` + độ lệch, và ``search_path`` của DB test
  đặt ``public`` trước ``pg_catalog`` -> ``now()`` trong truy vấn, trigger và ``DEFAULT now()``
  (gắn lúc migration tạo bảng) cùng giờ giả với Python. Không có biến -> không làm gì, DB test
  được trả về như cũ.

Test cần một giờ cố định riêng thì vẫn tự đóng băng đồng hồ engine (``booking_engine.common``).
"""

import os
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

ENV = "TEST_FAKE_NOW"
SETTING = "caulong.clock_offset"

_traveller = None


def start() -> None:
    """Bật giờ giả nếu có ``TEST_FAKE_NOW`` (gọi một lần, trước khi import app)."""
    global _traveller
    raw = os.environ.get(ENV)
    if not raw or _traveller is not None:
        return
    import time_machine

    target = datetime.fromisoformat(raw)
    if target.tzinfo is None:
        raise SystemExit(f"{ENV} phải có múi giờ, vd 2026-11-10T23:59:30+07:00")
    _traveller = time_machine.travel(target, tick=True)
    _traveller.start()
    datetime.now(UTC)  # time-machine bắt đầu đếm từ lần đọc giờ đầu tiên


def _offset_seconds() -> float:
    """Giờ giả − giờ thật, đo lúc dùng (không đo lúc bật: đồng hồ giả bắt đầu đếm muộn hơn)."""
    from time_machine import escape_hatch

    return datetime.now(UTC).timestamp() - escape_hatch.time.time()


def active() -> bool:
    return _traveller is not None


async def configure_database(server: AsyncConnection, database: str) -> None:
    """Đặt (hoặc gỡ) giờ giả cho DB test – chạy trước khi engine của app mở kết nối."""
    name = database.replace('"', '""')
    if active():
        await server.execute(
            text(f'ALTER DATABASE "{name}" SET search_path = "$user", public, pg_catalog')
        )
        await server.execute(
            text(f"ALTER DATABASE \"{name}\" SET {SETTING} = '{_offset_seconds():.3f} seconds'")
        )
    else:
        await server.execute(text(f'ALTER DATABASE "{name}" RESET search_path'))
        await server.execute(text(f'ALTER DATABASE "{name}" RESET {SETTING}'))


async def install_now(conn: AsyncConnection) -> None:
    """``public.now()`` lệch giờ – tạo sau khi dựng lại schema ``public``, trước migration."""
    if not active():
        return
    await conn.execute(
        text(
            "CREATE OR REPLACE FUNCTION public.now() RETURNS timestamptz LANGUAGE sql STABLE AS "
            f"$$ SELECT pg_catalog.now() + coalesce(current_setting('{SETTING}', true), "
            "'0 seconds')::interval $$"
        )
    )
