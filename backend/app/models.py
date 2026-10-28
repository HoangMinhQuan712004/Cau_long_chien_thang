"""Import mọi model để Alembic autogenerate nhìn thấy đầy đủ metadata."""

from app.core.audit import AuditLog
from app.core.db import Base
from app.core.idempotency import IdempotencyKey
from app.modules.auth.models import User
from app.modules.booking_engine import models as booking_engine_models
from app.modules.content.models import Post
from app.modules.members.models import Customer
from app.modules.payments.models import BankTransaction

__all__ = [
    "AuditLog",
    "BankTransaction",
    "Base",
    "Customer",
    "IdempotencyKey",
    "Post",
    "User",
    "booking_engine_models",
]
