"""Tab Phân quyền (bước 3): Admin đặt quyền cho Nhân viên (Admin luôn toàn quyền).

Quyền lưu ở ``role_permission`` (bước 2). ``roles.manage`` (chỉ Admin) và ``payments.simulate``
(link dev) không hiện, không gán / bỏ được.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit, audit_change, audit_detail
from app.core.errors import AppError
from app.core.middleware import require_origin
from app.core.permissions import DEFAULT_ROLE_PERMS, Perm, Principal, require
from app.modules.auth.deps import SessionDep
from app.modules.auth.models import RolePermission

# Chỉ Nhân viên chỉnh được; giữ dạng ``/{role}`` để sau mở rộng vai khác
EditableRole = Literal["staff"]
ROLE_NAMES: dict[str, str] = {"staff": "Nhân viên"}
# Không hiện, không gán / bỏ được. CONTENT_MANAGE: chưa có màn quản lý Tin tức – có màn thì bỏ khỏi
# đây và thêm lại nhóm "Tin tức" vào _GROUPS
HIDDEN = frozenset(
    {
        Perm.ROLES_MANAGE,
        Perm.SETTINGS_MENU,
        Perm.SETTINGS_SITE,
        Perm.PAYMENTS_SIMULATE,
        Perm.CONTENT_MANAGE,
    }
)

# (key, nhãn nhóm, [(quyền, nhãn, gợi ý)]) – theo nhóm menu khu quản trị
_GROUPS: tuple[tuple[str, str, tuple[tuple[Perm, str, str | None], ...]], ...] = (
    (
        "booking",
        "Đặt sân",
        (
            (Perm.BOOKING_CALENDAR_VIEW, "Xem lịch đặt sân", None),
            (Perm.BOOKING_RESOURCES_VIEW, "Xem danh sách sân", "Cần cho lịch và popup đặt sân"),
            (Perm.BOOKING_QUOTE, "Xem giá khi đặt", None),
            (Perm.BOOKING_SEARCH, "Tìm booking", None),
            (Perm.BOOKING_COUNTER_CREATE, "Đặt sân tại quầy", None),
            (Perm.BOOKING_RECURRING, "Đặt sân định kỳ cho khách", None),
            (Perm.BOOKING_ORDERS_VIEW, "Xem màn Đơn đặt sân", None),
            (Perm.BOOKING_ITEM_VIEW, "Xem thông tin booking / vé", None),
            (Perm.BOOKING_TICKET_CREATE, "Đăng ký vé tại quầy", None),
            (Perm.BOOKING_SESSION_VIEW, "Xem sự kiện", None),
            (Perm.BOOKING_SESSION_MANAGE, "Tạo / xóa sự kiện", None),
        ),
    ),
    (
        "payment",
        "Thu tiền",
        (
            (Perm.BOOKING_COLLECT, "Thu tiền", None),
            (Perm.BOOKING_UNCOLLECTIBLE, "Đánh dấu không thu được", None),
            (Perm.BOOKING_TRANSACTIONS_VIEW, "Xem lịch sử giao dịch", None),
        ),
    ),
    (
        "member",
        "Hội viên",
        (
            (Perm.MEMBER_SEARCH, "Tìm hội viên", None),
            (Perm.MEMBER_MANAGE, "Xem, thêm, sửa hội viên", None),
            (Perm.MEMBER_STATUS, "Đổi trạng thái Hoạt động / Ngừng", None),
            (Perm.RACKET_MANAGE, "Quản lý danh mục vợt", None),
        ),
    ),
    (
        "court",
        "Sân & giá",
        ((Perm.BOOKING_CONFIG_MANAGE, "Sửa sân, giờ mở cửa, bảng giá, ngày Lễ", None),),
    ),
    ("report", "Báo cáo", ((Perm.REPORTS_VIEW, "Xem báo cáo & phân tích", None),)),
    (
        "staff",
        "Nhân viên",
        ((Perm.STAFF_MANAGE, "Quản lý tài khoản nhân viên", "Tạo, khóa, đặt lại mật khẩu"),),
    ),
    (
        "settings",
        "Thanh toán",
        ((Perm.PAYMENTS_SETTINGS, "Cài đặt tài khoản nhận tiền", None),),
    ),
    ("records", "Kỷ lục", ((Perm.RECORDS_VIDEO_MANAGE, "Gắn / gỡ video kỷ lục", None),)),
    ("audit", "Nhật ký", ((Perm.AUDIT_LOG_VIEW, "Xem lịch sử thao tác", None),)),
)
LABELS: dict[Perm, str] = {p: label for _, _, items in _GROUPS for p, label, _ in items}
EDITABLE = frozenset(LABELS)
CATALOG_ORDER: tuple[Perm, ...] = tuple(LABELS)
# Perm mới phải được xếp nhóm ở đây (hoặc ẩn) – thiếu thì lỗi ngay lúc khởi động
if EDITABLE | HIDDEN != frozenset(Perm) or EDITABLE & HIDDEN:
    raise RuntimeError("Phân quyền: có Perm chưa xếp nhóm (hoặc vừa ẩn vừa hiện) trong roles.py")


class PermOut(BaseModel):
    key: str
    label: str
    hint: str | None = None


class PermGroupOut(BaseModel):
    key: str
    label: str
    perms: list[PermOut]


class RolesOut(BaseModel):
    groups: list[PermGroupOut]
    roles: dict[EditableRole, list[str]] = Field(description="Quyền hiện có của vai (chỉ staff)")
    defaults: dict[EditableRole, list[str]] = Field(
        description="Quyền mặc định của vai (nút Về mặc định: FE đặt bản nháp rồi PUT)"
    )


class RolePermsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    perms: list[str] = Field(max_length=100)


async def _role_perms(session: AsyncSession, role: str) -> set[Perm]:
    rows = await session.scalars(select(RolePermission.perm).where(RolePermission.role == role))
    return {Perm(p) for p in rows if p in EDITABLE}


async def get_matrix(session: AsyncSession) -> RolesOut:
    groups = [
        PermGroupOut(
            key=key,
            label=label,
            perms=[PermOut(key=p.value, label=name, hint=hint) for p, name, hint in items],
        )
        for key, label, items in _GROUPS
    ]
    roles = {role: sorted(await _role_perms(session, role)) for role in ROLE_NAMES}
    # Theo thứ tự catalog; chỉ quyền chỉnh được (bỏ quyền ẩn / chỉ Admin)
    defaults = {
        role: [p.value for p in CATALOG_ORDER if p in DEFAULT_ROLE_PERMS[role]]
        for role in ROLE_NAMES
    }
    return RolesOut(groups=groups, roles=roles, defaults=defaults)


async def set_role_perms(
    session: AsyncSession, actor: AuditActor, role: EditableRole, perms: list[str]
) -> RolesOut:
    """Đặt lại tập quyền của vai (commit). Quyền lạ / ẩn -> 422 E-ROLE-1; dòng ẩn giữ nguyên."""
    allowed = {e.value for e in EDITABLE}
    unknown = sorted({p for p in perms if p not in allowed})
    if unknown:
        raise AppError("E-ROLE-1", f"Quyền không hợp lệ: {', '.join(unknown)}.", 422)
    wanted = {Perm(p) for p in perms}
    # Hai lần lưu cùng lúc (2 tab / 2 Admin) -> lần lượt, không trộn hai tập quyền
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('role_permission'))"))
    before = await _role_perms(session, role)
    await session.execute(
        delete(RolePermission).where(
            RolePermission.role == role, RolePermission.perm.in_([p.value for p in EDITABLE])
        )
    )
    session.add_all(RolePermission(role=role, perm=p.value) for p in sorted(wanted))
    changes = [audit_change(LABELS[p], "Có", "Không") for p in sorted(before - wanted)] + [
        audit_change(LABELS[p], "Không", "Có") for p in sorted(wanted - before)
    ]
    if changes:
        audit(
            session,
            actor,
            "roles.update",
            "role",
            role,
            audit_detail(role, ROLE_NAMES[role], changes),
        )
    await session.commit()
    return await get_matrix(session)


# ---------------------------------------------------------------- router (chỉ Admin)

router = APIRouter(prefix="/admin/roles", tags=["admin: roles"])
RolesManager = Annotated[Principal, Depends(require(Perm.ROLES_MANAGE))]


@router.get("", response_model=RolesOut)
async def read_roles(_: RolesManager, session: SessionDep):
    """Quyền của Nhân viên theo nhóm (không có roles.manage, payments.simulate)."""
    return await get_matrix(session)


@router.put("/{role}", response_model=RolesOut, dependencies=[Depends(require_origin)])
async def update_role(role: EditableRole, data: RolePermsIn, p: RolesManager, session: SessionDep):
    """Đặt lại quyền của Nhân viên; có hiệu lực ngay. 422 E-ROLE-1 (quyền lạ) / vai khác staff."""
    return await set_role_perms(session, p.audit_actor, role, data.perms)
