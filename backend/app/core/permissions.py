"""Bảng quyền tập trung (ADR-004 §3, S6).

Router khai báo quyền bằng ``Depends(require(Perm.X))`` – không so vai trực tiếp.
Thiếu đăng nhập -> 401 ``E-AUTH-1``; thiếu quyền -> 403 ``E-AUTH-2``.
"""

import enum
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends

from app.core.errors import AppError
from app.modules.auth.deps import AuthStateDep, unauthenticated
from app.modules.auth.sessions import actor_label, actor_type_of


class Perm(enum.StrEnum):
    BOOKING_RESOURCES_VIEW = "booking.resources.view"  # danh mục sân (lịch, popup)
    BOOKING_CONFIG_MANAGE = "booking.config.manage"  # sân, giờ, bảng giá, Lễ/Tết
    BOOKING_QUOTE = "booking.quote"  # báo giá khung (popup Đặt sân)
    BOOKING_CALENDAR_VIEW = "booking.calendar.view"
    BOOKING_SEARCH = "booking.search"
    BOOKING_COUNTER_CREATE = "booking.counter.create"
    BOOKING_RECURRING = "booking.recurring"  # đặt sân định kỳ cho khách (chỉ Admin, T-035)
    BOOKING_ITEM_VIEW = "booking.item.view"  # Thông tin booking / vé
    BOOKING_TICKET_CREATE = "booking.ticket.create"  # đăng ký vé tại quầy
    BOOKING_SESSION_VIEW = "booking.session.view"
    BOOKING_SESSION_MANAGE = "booking.session.manage"  # tạo / xóa sự kiện
    BOOKING_COLLECT = "booking.collect"
    BOOKING_UNCOLLECTIBLE = "booking.uncollectible"
    BOOKING_TRANSACTIONS_VIEW = "booking.transactions.view"
    MEMBER_SEARCH = "member.search"
    MEMBER_MANAGE = "member.manage"  # màn Hội viên: xem, thêm, sửa, hồ sơ tạm, chuyển (T-014)
    MEMBER_STATUS = "member.status"  # đổi trạng thái Hoạt động / Ngừng của hội viên (chỉ Admin)
    RACKET_MANAGE = "racket.manage"  # danh mục vợt: thêm / sửa / ẩn (chỉ Admin)
    PAYMENTS_SIMULATE = "payments.simulate"  # giả lập tiền về (chỉ link dev)
    STAFF_MANAGE = "staff.manage"  # tài khoản nhân viên (chỉ Admin, T-013)
    CONTENT_MANAGE = "content.manage"  # tin tức / trang nội dung (chỉ Admin)
    PAYMENTS_SETTINGS = "payments.settings"  # tài khoản nhận tiền, khóa SePay (chỉ Admin, T-012)
    AUDIT_LOG_VIEW = "audit_log.view"  # Lịch sử thao tác (chỉ Admin, SRS Lịch sử thao tác BR-001)
    RECORDS_VIDEO_MANAGE = "records.video.manage"  # gắn / gỡ video kỷ lục (chỉ Admin, T-046)
    REPORTS_VIEW = "reports.view"  # Báo cáo & phân tích (chỉ Admin, SRS Báo cáo BR-001)


# Vai hiện có: admin = Admin (chủ sân), staff = nhân viên (NV001…), customer = khách
ROLE_PERMS: dict[str, frozenset[Perm]] = {
    "admin": frozenset(Perm),
    "staff": frozenset(
        {
            Perm.BOOKING_RESOURCES_VIEW,
            Perm.BOOKING_QUOTE,
            Perm.BOOKING_CALENDAR_VIEW,
            Perm.BOOKING_SEARCH,
            Perm.BOOKING_COUNTER_CREATE,
            Perm.BOOKING_ITEM_VIEW,
            Perm.BOOKING_TICKET_CREATE,
            Perm.BOOKING_SESSION_VIEW,
            Perm.BOOKING_COLLECT,
            Perm.BOOKING_UNCOLLECTIBLE,
            Perm.MEMBER_SEARCH,
            Perm.MEMBER_MANAGE,
        }
    ),
    "member": frozenset(),
}

# Nhãn hiển thị người thao tác (nhật ký, "người thu") – không lộ email / tên đăng nhập
ROLE_LABELS = {"admin": "Admin", "staff": "Nhân viên", "member": "Khách đặt online"}


@dataclass(frozen=True)
class Principal:
    """Người đang thao tác – truyền xuống service/engine thay cho ORM ``User``."""

    actor_type: str  # admin | staff | customer (vai member – xem ``actor_type_of``)
    actor_id: int
    label: str
    perms: frozenset[Perm]
    session_id: int | None = None  # phiên quản trị (Admin / NV); None với khách

    def has(self, perm: Perm) -> bool:
        return perm in self.perms

    @property
    def key(self) -> str:
        return f"{self.actor_type}:{self.actor_id}"


def principal_of(user, session_id: int | None = None) -> Principal:
    role = str(user.role)
    return Principal(
        actor_type=actor_type_of(role),
        actor_id=user.id,
        label=actor_label(user) if role != "member" else ROLE_LABELS["member"],
        perms=ROLE_PERMS.get(role, frozenset()),
        session_id=session_id,
    )


async def get_optional_principal(state: AuthStateDep) -> Principal | None:
    """Phiên quản trị (Admin / NV) hoặc JWT khách – ADR-008 §3."""
    if state.user is None:
        return None
    return principal_of(state.user, state.admin_session.id if state.admin_session else None)


OptionalPrincipal = Annotated[Principal | None, Depends(get_optional_principal)]


class require:  # noqa: N801 – dùng như hàm: Depends(require(Perm.X))
    """Dependency kiểm quyền; giữ ``perm`` để test quét được mọi route."""

    def __init__(self, perm: Perm):
        self.perm = perm

    async def __call__(self, principal: OptionalPrincipal, state: AuthStateDep) -> Principal:
        if principal is None:
            raise unauthenticated(state.reason)
        if not principal.has(self.perm):
            raise AppError("E-AUTH-2", "Không có quyền thực hiện thao tác này", 403)
        return principal
