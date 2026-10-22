from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict, Unauthorized
from app.core.security import hash_password, verify_password
from app.modules.auth.models import Role, User
from app.modules.auth.schemas import RegisterIn


async def get_user(session: AsyncSession, user_id: int) -> User | None:
    return await session.get(User, user_id)


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == email.lower()))


async def create_user(session: AsyncSession, data: RegisterIn, role: Role = Role.CUSTOMER) -> User:
    if await get_user_by_email(session, data.email):
        raise Conflict("Email đã được sử dụng")
    user = User(
        email=data.email.lower(),
        full_name=data.full_name,
        phone=data.phone,
        hashed_password=hash_password(data.password),
        role=role,
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def authenticate(session: AsyncSession, email: str, password: str) -> User:
    user = await get_user_by_email(session, email)
    if not user or not verify_password(password, user.hashed_password):
        raise Unauthorized("Email hoặc mật khẩu không đúng")
    if not user.is_active:
        raise Unauthorized("Tài khoản đã bị khóa")
    return user
