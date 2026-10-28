from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from pydantic_core import PydanticCustomError

from app.modules.auth.models import Role
from app.modules.auth.utils import normalize_phone, password_problems, password_rule_message


def _valid_phone(value: str) -> str:
    phone = normalize_phone(value)
    if phone is None:
        raise PydanticCustomError("invalid_phone", "Số điện thoại không hợp lệ.")
    return phone


# SĐT chuẩn hóa 0xxxxxxxxx
Phone = Annotated[str, Field(max_length=20), AfterValidator(_valid_phone)]


def _strong_password(value: str) -> str:
    if problems := password_problems(value):
        # type riêng, không tiền tố "Value error" -> FE hiện nguyên câu
        raise PydanticCustomError("weak_password", password_rule_message(problems))
    return value


# Mật khẩu mới (đăng ký, tạo / đặt lại NV, đặt lại qua OTP, lệnh trên server)
NewPassword = Annotated[
    str,
    Field(
        max_length=128,
        description="≥ 8 ký tự, có ít nhất 1 chữ in hoa và 1 chữ số hoặc ký tự đặc biệt",
    ),
    AfterValidator(_strong_password),
]


class _In(BaseModel):
    # Không tự cắt khoảng trắng (mật khẩu giữ nguyên văn); trường lạ -> 422
    model_config = ConfigDict(extra="forbid")


class RegisterIn(_In):
    full_name: str = Field(min_length=1, max_length=255)
    phone: Phone
    password: NewPassword


class SignInIn(_In):
    """Ô "Số điện thoại hoặc tên đăng nhập" – chuẩn hóa ở service."""

    login: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    """Tài khoản khách – chỉ trả cho **chính người đó** (SĐT đầy đủ của mình)."""

    id: int
    phone: str | None
    phone_verified: bool
    username: str | None
    full_name: str
    google_email: str | None
    role: Role
    is_active: bool


class AdminAccountOut(BaseModel):
    """Thẻ tài khoản khu quản trị."""

    kind: Literal["admin", "staff"]
    display_name: str
    role_label: str
    staff_code: str | None = None


class AdminSessionOut(BaseModel):
    account: AdminAccountOut
    expires_at: datetime


class CustomerSignInOut(BaseModel):
    kind: Literal["customer"] = "customer"
    account: UserOut


class AdminSignInOut(AdminSessionOut):
    kind: Literal["admin"] = "admin"


# ``kind`` quyết định FE đi khu nào (admin gồm nhân viên)
SignInOut = Annotated[CustomerSignInOut | AdminSignInOut, Field(discriminator="kind")]


def user_out(user) -> UserOut:
    return UserOut(
        id=user.id,
        phone=user.phone,
        phone_verified=user.phone_verified_at is not None,
        username=user.username,
        full_name=user.full_name,
        google_email=user.google_email,
        role=user.role,
        is_active=user.is_active,
    )
