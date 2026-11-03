"""Hồ sơ hội viên mẫu cho link dev (T-034) – chỉ ``app.scripts.seed_demo`` gọi (qua ``api``).

Dấu mẫu: họ tên bắt đầu bằng ``DEMO_NAME_PREFIX`` **và** SĐT trong dải ``09990000xx``. Xóa chỉ khi
có đủ hai dấu – hồ sơ thật không bao giờ bị đụng.
"""

from dataclasses import dataclass

from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.members.models import Customer
from app.modules.members.profiles import next_code

DEMO_NAME_PREFIX = "Mẫu · "
DEMO_PHONE_PREFIX = "09990000"


def demo_phone(n: int) -> str:
    return f"{DEMO_PHONE_PREFIX}{n:02d}"


@dataclass(frozen=True)
class DemoMemberSpec:
    n: int  # 1..99 -> SĐT 09990000nn, tên "Mẫu · Hội viên nn"
    tier: str | None
    show_on_records: bool
    nickname: str | None = None


@dataclass(frozen=True)
class DemoMember:
    customer_id: int
    phone: str
    full_name: str
    member_code: str
    tier: str | None


def _is_demo():
    return Customer.phone.like(f"{DEMO_PHONE_PREFIX}%") & Customer.full_name.startswith(
        DEMO_NAME_PREFIX
    )


async def foreign_demo_phones(session: AsyncSession) -> list[str]:
    """SĐT trong dải mẫu đang thuộc hồ sơ **không** có dấu mẫu (hồ sơ thật) -> script dừng."""
    rows = await session.scalars(
        select(Customer.phone).where(
            Customer.phone.like(f"{DEMO_PHONE_PREFIX}%"),
            ~Customer.full_name.startswith(DEMO_NAME_PREFIX),
        )
    )
    return list(rows)


async def demo_member_ids(session: AsyncSession) -> list[int]:
    return list(await session.scalars(select(Customer.id).where(_is_demo())))


async def seed_members(session: AsyncSession, specs: list[DemoMemberSpec]) -> list[DemoMember]:
    """Tạo hội viên mẫu (Hoạt động, mã HV thật cấp tuần tự). Không commit."""
    created: list[DemoMember] = []
    for spec in specs:
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('member_code'))"))
        c = Customer(
            kind="member",
            member_code=await next_code(session),
            full_name=f"{DEMO_NAME_PREFIX}Hội viên {spec.n:02d}",
            phone=demo_phone(spec.n),
            tier=spec.tier,
            nickname=spec.nickname,
            is_active=True,
            show_on_records=spec.show_on_records,
            source="counter",
        )
        session.add(c)
        await session.flush()
        created.append(DemoMember(c.id, c.phone, c.full_name, c.member_code or "", c.tier))
    return created


async def purge_demo(session: AsyncSession) -> int:
    """Xóa hồ sơ mẫu (đủ hai dấu). Không commit. Trả số hồ sơ đã xóa."""
    result = await session.execute(delete(Customer).where(_is_demo()))
    return result.rowcount or 0
