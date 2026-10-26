"""Import mọi model để Alembic autogenerate nhìn thấy đầy đủ metadata."""

from app.core.audit import AuditLog
from app.core.db import Base
from app.core.idempotency import IdempotencyKey
from app.modules.auth.models import User
from app.modules.booking_engine import models as booking_engine_models
from app.modules.bookings.models import Booking, BookingSlot
from app.modules.content.models import Post
from app.modules.courts.models import Court, PriceRule
from app.modules.payments.models import Payment

__all__ = [
    "AuditLog",
    "Base",
    "Booking",
    "BookingSlot",
    "Court",
    "IdempotencyKey",
    "Payment",
    "Post",
    "PriceRule",
    "User",
    "booking_engine_models",
]
