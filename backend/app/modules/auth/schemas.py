from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.modules.auth.models import Role


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=20)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    phone: str | None
    role: Role
    is_active: bool


class UserListItem(BaseModel):
    """Dòng danh sách tài khoản: SĐT đã che ở server (ADR-004 S12)."""

    id: int
    email: str
    full_name: str
    phone_masked: str | None
    role: Role
    is_active: bool


class StaffCreateIn(RegisterIn):
    role: Role = Role.STAFF
