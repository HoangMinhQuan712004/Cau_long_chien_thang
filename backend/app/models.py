"""Import mọi model để Alembic autogenerate nhìn thấy đầy đủ metadata."""

from app.core.db import Base
from app.modules.auth.models import (
    AdminSession,
    AuditLog,
    LoginFailure,
    PasswordResetCode,
    PasswordResetRequest,
    RegisterRequest,
    User,
)
from app.modules.bookings.models import Booking, BookingSlot
from app.modules.content.models import Post
from app.modules.courts.models import Court, PriceRule
from app.modules.payments.models import Payment

__all__ = [
    "AdminSession",
    "AuditLog",
    "Base",
    "Booking",
    "LoginFailure",
    "PasswordResetCode",
    "PasswordResetRequest",
    "RegisterRequest",
    "BookingSlot",
    "Court",
    "Payment",
    "Post",
    "PriceRule",
    "User",
]
