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
    must_change_password: bool = Field(
        description="Tài khoản hội viên chưa đổi mật khẩu ban đầu -> chuyển trang đổi mật khẩu"
    )
    is_member: bool = Field(
        default=False,
        description="Có hồ sơ hội viên cùng SĐT (đã xác minh) -> vào được khu hội viên (T-016)",
    )


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
    kind: Literal["member"] = "member"
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
        must_change_password=user.must_change_password,
    )


# ---------- OTP: quên mật khẩu, xác minh SĐT ----------

OtpDigits = Annotated[str, Field(pattern=r"^\d{6}$")]


class PhoneIn(_In):
    phone: Phone


class OtpSentOut(BaseModel):
    resend_after: int = Field(description="Giây tới lúc được gửi lại mã")
    test_otp: str | None = Field(
        default=None, description="Chỉ khi OTP_TEST_MODE (link dev) và là mã của khách"
    )


class PhoneOtpIn(_In):
    phone: Phone
    otp: OtpDigits


class ResetTokenOut(BaseModel):
    reset_token: str


class PasswordChangeIn(_In):
    """Đổi mật khẩu của khách; ``current_password`` không cần khi đang bắt đổi lần đầu."""

    new_password: NewPassword
    current_password: str | None = Field(default=None, max_length=128)


class ResetConfirmIn(_In):
    reset_token: str = Field(min_length=1, max_length=128)
    password: NewPassword


# ---------- Google, xác minh SĐT của khách ----------


class GoogleSignInIn(_In):
    credential: str = Field(min_length=1, max_length=4096, description="ID token của Google")


class PhoneVerifyOut(BaseModel):
    merged: bool = Field(description="SĐT đã thuộc tài khoản khác -> đã gộp tài khoản Google vào")
    password_cleared: bool = Field(
        description="Gộp vào tài khoản có mật khẩu -> mật khẩu đó đã bị hủy (đăng nhập bằng Google "
        "hoặc Quên mật khẩu)"
    )
    account: UserOut
    became_member: bool = Field(
        default=False, description="Vừa thành hội viên ở lần xác minh này (T-021 R1)"
    )
    member_code: str | None = Field(default=None, description="Mã HV của tài khoản (nếu có)")


# ---------- Đăng ký 2 bước bằng OTP (T-021) ----------


class RegisterRequestIn(_In):
    full_name: str = Field(min_length=1, max_length=100)
    phone: Phone
    password: NewPassword


class RegisterVerifyIn(_In):
    phone: Phone
    otp: OtpDigits


class RegisterOut(BaseModel):
    account: UserOut
    member_code: str = Field(description="Mã HV – tài khoản đăng ký xong là hội viên (R1)")
    upgraded_from_temp: bool = Field(
        description="SĐT đã có hồ sơ tạm -> nâng lên hội viên, giữ lịch sử đặt sân"
    )
