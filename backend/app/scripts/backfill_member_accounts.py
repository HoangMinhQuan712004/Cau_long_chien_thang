"""Tạo tài khoản đăng nhập cho hội viên đã có (T-015) – chạy một lần, chạy lại không sinh trùng.

    cd backend && .venv/bin/python -m app.scripts.backfill_member_accounts

Theo đúng luồng Thêm hội viên: SĐT chưa có tài khoản -> tạo (mật khẩu = SĐT, bắt đổi lần đầu);
đã có tài khoản khách -> giữ nguyên mật khẩu; Admin / NV -> không đụng. Hội viên Ngừng -> tài khoản
khách cùng SĐT ở trạng thái khóa.
"""

import asyncio

from sqlalchemy import select

import app.models  # noqa: F401
from app.core.db import SessionLocal
from app.modules.auth import api as auth
from app.modules.members.models import Customer


async def backfill() -> tuple[int, int]:
    """(số tài khoản tạo mới, số hội viên bỏ qua vì SĐT đã có tài khoản)."""
    created = skipped = 0
    async with SessionLocal() as session:
        members = await session.scalars(
            select(Customer).where(Customer.kind == "member").order_by(Customer.member_code)
        )
        for c in list(members):
            if await auth.ensure_customer_account(session, c.phone, c.full_name, c.is_active):
                created += 1
            else:
                skipped += 1
            if not c.is_active:
                await auth.set_customer_account_active(session, c.phone, False)
        await session.commit()
    return created, skipped


async def main() -> None:
    created, skipped = await backfill()
    print(f"Tài khoản hội viên: tạo mới {created}, bỏ qua {skipped} (SĐT đã có tài khoản).")


if __name__ == "__main__":
    asyncio.run(main())
