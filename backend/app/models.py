"""Import mọi model để Alembic autogenerate nhìn thấy đầy đủ metadata."""

from app.core.audit import AuditLog
from app.core.db import Base
from app.core.idempotency import IdempotencyKey
from app.core.settings_store import AppSetting
from app.modules.auth.models import AdminSession, OtpCode, RolePermission, User, UserAvatar
from app.modules.booking_engine import models as booking_engine_models
from app.modules.content.models import Post
from app.modules.member_inbox.models import MemberNotification
from app.modules.members.models import Customer, CustomerAvatar, Racket
from app.modules.payments.models import BankTransaction
from app.modules.play_rooms.models import PlayMatch, PlayRoom, PlayRoomMember, PlayRoomRequest
from app.modules.records.models import SpeedRecord

__all__ = [
    "AdminSession",
    "AppSetting",
    "OtpCode",
    "AuditLog",
    "BankTransaction",
    "Base",
    "Customer",
    "CustomerAvatar",
    "Racket",
    "RolePermission",
    "IdempotencyKey",
    "MemberNotification",
    "PlayMatch",
    "PlayRoom",
    "PlayRoomMember",
    "PlayRoomRequest",
    "Post",
    "SpeedRecord",
    "User",
    "UserAvatar",
    "booking_engine_models",
]
