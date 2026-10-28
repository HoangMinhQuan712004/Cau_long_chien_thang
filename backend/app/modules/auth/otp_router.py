"""API OTP Zalo: quên mật khẩu, xác minh SĐT."""

from fastapi import APIRouter, HTTPException, Response, status

from app.core.config import settings
from app.core.errors import coded_error
from app.modules.auth import service
from app.modules.auth.cookies import (
    set_auth_cookies,
)
from app.modules.auth.deps import (
    ClientIP,
    CurrentUser,
    SessionDep,
)
from app.modules.auth.schemas import (
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    PasswordResetRequestOut,
    PasswordResetVerifyIn,
    PasswordResetVerifyOut,
    PhoneVerifyIn,
    PhoneVerifyOut,
    PhoneVerifyRequestIn,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


_OTP_ERRORS: dict[service.OtpErrorCode, tuple[int, str]] = {
    "otp_rate_limited": (
        status.HTTP_429_TOO_MANY_REQUESTS,
        "Bạn đã yêu cầu gửi mã quá nhiều lần. Vui lòng thử lại sau.",
    ),
    "otp_invalid": (status.HTTP_400_BAD_REQUEST, "Mã xác minh không đúng."),
    "otp_expired": (
        status.HTTP_400_BAD_REQUEST,
        "Mã xác minh đã hết hạn hoặc không còn hiệu lực. Vui lòng gửi lại mã.",
    ),
    "reset_token_invalid": (
        status.HTTP_400_BAD_REQUEST,
        "Phiên đặt lại mật khẩu đã hết hạn. Vui lòng làm lại từ đầu.",
    ),
    "phone_already_set": (status.HTTP_409_CONFLICT, "Tài khoản đã có số điện thoại."),
    # một câu chung, không lộ chủ SĐT
    "phone_unusable": (status.HTTP_409_CONFLICT, "Số điện thoại không dùng được."),
    "merge_has_bookings": (
        status.HTTP_409_CONFLICT,
        "Không gộp được tài khoản. Vui lòng liên hệ sân để được hỗ trợ.",
    ),
}


def _otp_http_error(error: service.OtpError) -> HTTPException:
    return coded_error(
        error.code,
        *_OTP_ERRORS[error.code],
        retry_after=error.retry_after,
        attempts_left=error.attempts_left,
    )


@router.post(
    "/password-reset/request",
    response_model=PasswordResetRequestOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={429: {"description": "code: otp_rate_limited (+ retry_after)"}},
)
async def request_password_reset(data: PasswordResetRequestIn, session: SessionDep, ip: ClientIP):
    """Luôn 202 như nhau dù SĐT chưa đăng ký – không lộ SĐT nào có tài khoản."""
    try:
        await service.request_password_reset(session, data.phone, ip)
    except service.OtpError as e:
        raise _otp_http_error(e) from e
    return PasswordResetRequestOut(resend_after=settings.OTP_RESEND_SECONDS)


@router.post(
    "/password-reset/verify",
    response_model=PasswordResetVerifyOut,
    responses={400: {"description": "code: otp_invalid (+ attempts_left) | otp_expired"}},
)
async def verify_password_reset(data: PasswordResetVerifyIn, session: SessionDep):
    try:
        token = await service.verify_password_reset(session, data.phone, data.otp)
    except service.OtpError as e:
        raise _otp_http_error(e) from e
    return PasswordResetVerifyOut(reset_token=token)


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={400: {"description": "code: reset_token_invalid"}},
)
async def confirm_password_reset(data: PasswordResetConfirmIn, session: SessionDep):
    try:
        await service.confirm_password_reset(session, data.reset_token, data.password)
    except service.OtpError as e:
        raise _otp_http_error(e) from e


@router.post(
    "/phone/request",
    response_model=PasswordResetRequestOut,
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        409: {"description": "code: phone_already_set"},
        429: {"description": "code: otp_rate_limited (+ retry_after)"},
    },
)
async def request_phone_verify(
    data: PhoneVerifyRequestIn, user: CurrentUser, session: SessionDep, ip: ClientIP
):
    """Khách chưa có SĐT (tài khoản Google) gửi mã xác minh SĐT – cần trước khi đặt sân."""
    try:
        await service.request_phone_verify(session, user, data.phone, ip)
    except service.OtpError as e:
        raise _otp_http_error(e) from e
    return PasswordResetRequestOut(resend_after=settings.OTP_RESEND_SECONDS)


@router.post(
    "/phone/verify",
    response_model=PhoneVerifyOut,
    responses={
        400: {"description": "code: otp_invalid (+ attempts_left) | otp_expired"},
        409: {"description": "code: phone_already_set | phone_unusable | merge_has_bookings"},
    },
)
async def verify_phone(
    data: PhoneVerifyIn, user: CurrentUser, response: Response, session: SessionDep
):
    """Mã đúng ⇒ SĐT gắn vào tài khoản; SĐT đã có tài khoản khách ⇒ gộp và đăng nhập sang đó."""
    try:
        result = await service.verify_phone(session, user, data.phone, data.otp)
    except service.OtpError as e:
        raise _otp_http_error(e) from e
    set_auth_cookies(response, result.account)
    return PhoneVerifyOut(
        merged=result.merged,
        password_cleared=result.password_cleared,
        account=UserOut.model_validate(result.account),
    )
