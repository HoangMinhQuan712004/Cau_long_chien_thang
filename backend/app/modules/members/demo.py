"""Hồ sơ hội viên mẫu cho link dev (T-034) – chỉ ``app.scripts.seed_demo`` gọi (qua ``api``).

Dấu mẫu: họ tên **đúng** "Mẫu · Hội viên NN" **và** SĐT trong dải ``09990000xx`` – riêng
"Mẫu · Hội viên 01" được dùng SĐT người dùng chọn (``DEMO_MEMBER_PHONE``, bổ sung 04/11). Xóa chỉ
khi đủ dấu – hồ sơ thật không bao giờ bị đụng (``--clear`` vẫn tìm được 01 khi không có biến).
"""

from dataclasses import dataclass

from sqlalchemy import delete, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.members.models import Customer
from app.modules.members.profiles import next_code

DEMO_NAME_PREFIX = "Mẫu · "
DEMO_PHONE_PREFIX = "09990000"
MAX_N = 99


def demo_phone(n: int) -> str:
    return f"{DEMO_PHONE_PREFIX}{n:02d}"


def demo_name(n: int) -> str:
    return f"{DEMO_NAME_PREFIX}Hội viên {n:02d}"


@dataclass(frozen=True)
class DemoMemberSpec:
    n: int  # 1..99 -> SĐT 09990000nn, tên "Mẫu · Hội viên nn"
    tier: str | None
    show_on_records: bool
    nickname: str | None = None
    racket: str | None = None


@dataclass(frozen=True)
class DemoMember:
    customer_id: int
    phone: str
    full_name: str
    member_code: str
    tier: str | None


def _is_demo():
    names = [demo_name(n) for n in range(1, MAX_N + 1)]
    return Customer.full_name.in_(names) & or_(
        Customer.phone.like(f"{DEMO_PHONE_PREFIX}%"), Customer.full_name == demo_name(1)
    )


async def foreign_demo_phones(session: AsyncSession, extra_phone: str | None = None) -> list[str]:
    """SĐT trong dải mẫu (và ``extra_phone``) đang thuộc hồ sơ **không** có dấu mẫu -> dừng."""
    phones = Customer.phone.like(f"{DEMO_PHONE_PREFIX}%")
    if extra_phone:
        phones = phones | (Customer.phone == extra_phone)
    rows = await session.scalars(select(Customer.phone).where(phones, ~_is_demo()))
    return list(rows)


async def demo_member_ids(session: AsyncSession) -> list[int]:
    return list(await session.scalars(select(Customer.id).where(_is_demo())))


async def demo_member_phones(session: AsyncSession) -> list[str]:
    """SĐT của hồ sơ mẫu hiện có (gồm SĐT riêng của 01 nếu có) – để xóa dữ liệu theo SĐT."""
    return list(await session.scalars(select(Customer.phone).where(_is_demo())))


async def seed_members(
    session: AsyncSession, specs: list[DemoMemberSpec], first_phone: str | None = None
) -> list[DemoMember]:
    """Tạo hội viên mẫu (Hoạt động, mã HV thật cấp tuần tự). ``first_phone``: SĐT của 01."""
    created: list[DemoMember] = []
    for spec in specs:
        await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('member_code'))"))
        c = Customer(
            kind="member",
            member_code=await next_code(session),
            full_name=demo_name(spec.n),
            phone=first_phone if spec.n == 1 and first_phone else demo_phone(spec.n),
            tier=spec.tier,
            nickname=spec.nickname,
            racket=spec.racket,
            is_active=True,
            show_on_records=spec.show_on_records,
            source="counter",
        )
        session.add(c)
        await session.flush()
        created.append(DemoMember(c.id, c.phone, c.full_name, c.member_code or "", c.tier))
    return created


async def purge_demo(session: AsyncSession) -> int:
    """Xóa hồ sơ mẫu (đủ dấu). Không commit. Trả số hồ sơ đã xóa."""
    result = await session.execute(delete(Customer).where(_is_demo()))
    return result.rowcount or 0
