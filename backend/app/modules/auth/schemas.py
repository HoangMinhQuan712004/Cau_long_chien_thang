from datetime import datetime
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from pydantic_core import PydanticCustomError

from app.modules.auth.models import Role
from app.modules.auth.utils import normalize_phone, password_problems, password_rule_message


def _valid_phone(value: str) -> str:
    phone = normalize_phone(value)
    if phone is None:
        raise ValueError("Số điện thoại không hợp lệ")
    return phone


# SĐT chuẩn hóa 0xxxxxxxxx
Phone = Annotated[str, Field(max_length=20), AfterValidator(_valid_phone)]


def _strong_password(value: str) -> str:
    if problems := password_problems(value):
        # type riêng, không tiền tố "Value error" ⇒ FE hiện nguyên câu
        raise PydanticCustomError("weak_password", password_rule_message(problems))
    return value


# Mật khẩu mới: đăng ký, đặt lại qua OTP, cấp/đặt lại cho nhân viên
NewPassword = Annotated[
    str,
    Field(
        max_length=128,
        description="8–128 ký tự, có ít nhất 1 chữ in hoa và 1 chữ số hoặc ký tự đặc biệt",
    ),
    AfterValidator(_strong_password),
]


class RegisterIn(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    phone: Phone
    password: NewPassword


class LoginIn(BaseModel):
    """Ô "Số điện thoại hoặc tên đăng nhập" – chuẩn hóa ở service (BR-002)."""

    login: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=128)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str | None
    username: str | None
    full_name: str
    # chỉ để hiện
    google_email: str | None
    role: Role
    is_active: bool


class AdminAccountOut(BaseModel):
    """Tài khoản quản trị hiển thị trên thẻ tài khoản (SRS mục II.5)."""

    kind: Literal["admin", "counter"]
    display_name: str
    role_label: str


class AdminSessionOut(BaseModel):
    account: AdminAccountOut
    expires_at: datetime


class CustomerSignInOut(BaseModel):
    kind: Literal["customer"] = "customer"
    account: UserOut


class AdminSignInOut(AdminSessionOut):
    kind: Literal["admin"] = "admin"


# `kind` quyết định đi khu nào (admin gồm nhân viên)
SignInOut = Annotated[CustomerSignInOut | AdminSignInOut, Field(discriminator="kind")]


# --- Quên mật khẩu (OTP Zalo) ---
class PasswordResetRequestIn(BaseModel):
    phone: Phone


class PasswordResetRequestOut(BaseModel):
    resend_after: int  # giây tới lúc được gửi lại mã


class PasswordResetVerifyIn(BaseModel):
    phone: Phone
    otp: str = Field(pattern=r"^\d{6}$")


class PasswordResetVerifyOut(BaseModel):
    reset_token: str


class PasswordResetConfirmIn(BaseModel):
    reset_token: str = Field(min_length=1, max_length=128)
    password: NewPassword


# --- Đăng nhập Google + xác minh SĐT ---
class GoogleSignInIn(BaseModel):
    credential: str = Field(min_length=1, max_length=4096, description="ID token từ Google")


class PhoneVerifyRequestIn(BaseModel):
    phone: Phone


class PhoneVerifyIn(BaseModel):
    phone: Phone
    otp: str = Field(pattern=r"^\d{6}$")


class PhoneVerifyOut(BaseModel):
    # đã gộp sang tài khoản có SĐT này
    merged: bool
    # mật khẩu cũ của tài khoản đích đã bị hủy
    password_cleared: bool
    account: UserOut
