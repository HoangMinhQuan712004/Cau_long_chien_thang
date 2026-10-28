"""Service auth – router/deps gọi qua `service.<hàm>`."""

from app.modules.auth.service.common import LoginError, LoginErrorCode
from app.modules.auth.service.google import GoogleErrorCode, GoogleSignInError, google_sign_in
from app.modules.auth.service.login import (
    RegisterRateLimited,
    SessionError,
    SessionErrorCode,
    admin_logout,
    create_user,
    get_customer,
    resolve_admin_session,
    sign_in,
    to_account,
)
from app.modules.auth.service.otp import (
    OtpError,
    OtpErrorCode,
    confirm_password_reset,
    request_password_reset,
    verify_password_reset,
)
from app.modules.auth.service.phone import PhoneVerifyResult, request_phone_verify, verify_phone

__all__ = [
    "GoogleErrorCode",
    "GoogleSignInError",
    "LoginError",
    "LoginErrorCode",
    "OtpError",
    "OtpErrorCode",
    "PhoneVerifyResult",
    "RegisterRateLimited",
    "SessionError",
    "SessionErrorCode",
    "admin_logout",
    "confirm_password_reset",
    "create_user",
    "get_customer",
    "google_sign_in",
    "request_password_reset",
    "request_phone_verify",
    "resolve_admin_session",
    "sign_in",
    "to_account",
    "verify_password_reset",
    "verify_phone",
]
