"""Dữ liệu thử Bảng xếp hạng tốc độ – CHỈ dev/local (T-030 AC6).

    python -m app.modules.records.seed_demo           # thêm số đo thử cho hội viên đang liên kết
    python -m app.modules.records.seed_demo --clear   # xóa mọi số đo thử (source_ref "demo:…")

Từ chối chạy khi ``ENV=production``. Số đo thử mang ``source_ref`` bắt đầu bằng ``demo:`` và
``device_id = "demo"`` để xóa được riêng. Chạy lại nhiều lần không trùng (``source_ref`` unique).
"""

import argparse
import asyncio
import secrets
import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert

from app.core.config import settings
from app.core.db import SessionLocal
from app.modules.members import api as members
from app.modules.records.models import SpeedRecord
from app.modules.records.service import eligible

DEMO_PREFIX = "demo:"
PER_MEMBER = 6
DAYS_BACK = 400  # rải qua tuần / tháng / năm hiện tại và năm trước


async def seed(per_member: int = PER_MEMBER) -> int:
    rng = secrets.SystemRandom()
    now = datetime.now(UTC)
    async with SessionLocal() as session:
        people = await eligible(session, set(await members.member_ids(session)))
        rows = []
        for cid in sorted(people):
            base = rng.randint(150, 300)
            for i in range(per_member):
                rows.append(
                    {
                        "customer_id": cid,
                        "speed_kmh": max(50, min(500, base + rng.randint(-40, 40))),
                        "measured_at": now - timedelta(minutes=rng.randint(10, DAYS_BACK * 1440)),
                        "device_id": "demo",
                        "source_ref": f"{DEMO_PREFIX}{cid}:{i}",
                    }
                )
        if rows:
            await session.execute(
                insert(SpeedRecord)
                .values(rows)
                .on_conflict_do_nothing(index_elements=[SpeedRecord.source_ref])
            )
        await session.commit()
    return len(rows)


async def clear() -> int:
    async with SessionLocal() as session:
        result = await session.execute(
            delete(SpeedRecord).where(SpeedRecord.source_ref.like(f"{DEMO_PREFIX}%"))
        )
        await session.commit()
    return result.rowcount or 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Số đo tốc độ thử (chỉ dev)")
    parser.add_argument("--clear", action="store_true", help="Xóa số đo thử")
    args = parser.parse_args(argv)
    if settings.is_production:
        print("Từ chối: không seed số đo thử khi ENV=production.", file=sys.stderr)
        return 2
    if args.clear:
        print(f"Đã xóa {asyncio.run(clear())} số đo thử.")
    else:
        print(f"Đã thêm tối đa {asyncio.run(seed())} số đo thử (bỏ qua dòng đã có).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
