"""Bảng quyền tập trung (ADR-004 §3, S6).

Router khai báo quyền bằng ``Depends(require(Perm.X))`` – không so vai trực tiếp.
Thiếu đăng nhập -> 401 ``E-AUTH-1``; thiếu quyền -> 403 ``E-AUTH-2``.
Admin luôn toàn quyền; quyền Nhân viên đọc từ bảng ``role_permission`` mỗi request (tab Phân
quyền đổi là có hiệu lực ngay, không cache).
"""

import enum
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor
from app.core.errors import AppError
from app.modules.auth.deps import AuthStateDep, SessionDep, unauthenticated
from app.modules.auth.models import RolePermission, User
from app.modules.auth.sessions import actor_label, actor_type_of


class Perm(enum.StrEnum):
    """Quyền khai báo ở route. Admin tự có Perm mới; muốn NV có sẵn thì Perm mới phải có migration
    thêm dòng ``role_permission`` (role ``staff``)."""

    BOOKING_RESOURCES_VIEW = "booking.resources.view"  # danh mục sân (lịch, popup)
    BOOKING_CONFIG_MANAGE = "booking.config.manage"  # sân, giờ, bảng giá, Lễ/Tết
    BOOKING_QUOTE = "booking.quote"  # báo giá khung (popup Đặt sân)
    BOOKING_CALENDAR_VIEW = "booking.calendar.view"
    BOOKING_SEARCH = "booking.search"
    BOOKING_COUNTER_CREATE = "booking.counter.create"
    BOOKING_ORDERS_VIEW = "booking.orders.view"  # màn Đơn đặt sân (chỉ Admin, T-041)
    BOOKING_RECURRING = "booking.recurring"  # đặt sân định kỳ cho khách (chỉ Admin, T-035)
    BOOKING_ITEM_VIEW = "booking.item.view"  # Thông tin booking / vé
    BOOKING_TICKET_CREATE = "booking.ticket.create"  # đăng ký vé tại quầy
    BOOKING_SESSION_VIEW = "booking.session.view"
    BOOKING_SESSION_MANAGE = "booking.session.manage"  # tạo / xóa sự kiện
    BOOKING_COLLECT = "booking.collect"
    BOOKING_UNCOLLECTIBLE = "booking.uncollectible"
    BOOKING_CANCEL = "booking.cancel"  # hủy booking / vé (chỉ Admin, T-051)
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
    ROLES_MANAGE = "roles.manage"  # tab Phân quyền: chỉ Admin, không gán được cho NV
    SETTINGS_MENU = "settings.menu"  # sắp thứ tự menu khu quản trị: chỉ Admin


ALL_PERMS = frozenset(Perm)
# Chỉ Admin có, không gán được cho NV
ADMIN_ONLY = frozenset({Perm.ROLES_MANAGE, Perm.SETTINGS_MENU, Perm.BOOKING_CANCEL})

# Quyền mặc định (= dữ liệu seed của migration role_permission) – lúc chạy đọc từ bảng.
# Vai: admin = Admin, staff = nhân viên (NV001…), member = khách
DEFAULT_ROLE_PERMS: dict[str, frozenset[Perm]] = {
    "admin": ALL_PERMS,
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
            Perm.BOOKING_CONFIG_MANAGE,
            Perm.BOOKING_TRANSACTIONS_VIEW,
            Perm.BOOKING_SESSION_MANAGE,
            Perm.RACKET_MANAGE,
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

    @property
    def audit_actor(self) -> AuditActor:
        """Người thao tác ghi vào ``audit_log``."""
        return AuditActor(type=self.actor_type, id=self.actor_id, label=self.label)


def principal_of(user, perms: frozenset[Perm], session_id: int | None = None) -> Principal:
    role = str(user.role)
    return Principal(
        actor_type=actor_type_of(role),
        actor_id=user.id,
        label=actor_label(user) if role != "member" else ROLE_LABELS["member"],
        perms=perms,
        session_id=session_id,
    )


async def load_perms(session: AsyncSession, user: User) -> frozenset[Perm]:
    """Admin: toàn quyền (không truy vấn); NV: đọc ``role_permission``; khách: rỗng."""
    role = str(user.role)
    if role == "admin":
        return ALL_PERMS
    if role != "staff":
        return frozenset()
    rows = await session.scalars(select(RolePermission.perm).where(RolePermission.role == role))
    known = {p.value for p in Perm}
    return frozenset(Perm(p) for p in rows if p in known) - ADMIN_ONLY


async def get_optional_principal(state: AuthStateDep, session: SessionDep) -> Principal | None:
    """Phiên quản trị (Admin / NV) hoặc JWT khách – ADR-008 §3."""
    if state.user is None:
        return None
    perms = await load_perms(session, state.user)
    return principal_of(state.user, perms, state.admin_session.id if state.admin_session else None)


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
