"""Thứ tự menu bên trái khu quản trị: Admin sắp chung cho mọi tài khoản (NV thấy cùng thứ tự,
trừ mục không có quyền). Lưu ở ``app_setting`` key ``admin_menu_order``; chưa lưu ⇒ mặc định.

Key menu do FE định nghĩa (``ADMIN_NAV`` trong ``admin/_components/forbidden.ts``); ``MenuKey``
xuất ra OpenAPI nên FE thêm mục mà quên thêm ở đây thì lỗi type lúc build.
"""

from typing import Annotated, Literal, get_args

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit, audit_change, audit_detail
from app.core.errors import AppError
from app.core.middleware import require_origin
from app.core.permissions import Perm, Principal, require
from app.core.settings_store import AppSetting, get_value
from app.modules.auth.deps import SessionDep

SETTING_KEY = "admin_menu_order"
# Thứ tự mặc định = thứ tự khai báo
MenuKey = Literal["baoCao", "san", "datSan", "hoiVien", "lichSu", "thanhToan", "nhanVien"]
MENU_KEYS: tuple[str, ...] = get_args(MenuKey)
MENU_LABELS = {
    "baoCao": "Báo cáo",
    "san": "Sân",
    "datSan": "Đặt sân",
    "hoiVien": "Hội viên",
    "lichSu": "Lịch sử giao dịch",
    "thanhToan": "Thanh toán",
    "nhanVien": "Nhân viên",
}


class MenuOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order: list[MenuKey]


class MenuOrderOut(BaseModel):
    order: list[MenuKey]


def _normalize(saved: object) -> list[str]:
    """Bỏ key không còn dùng / trùng, nối key mới (thêm sau khi lưu) vào cuối theo mặc định."""
    kept = [k for k in saved if k in MENU_KEYS] if isinstance(saved, list) else []
    kept = list(dict.fromkeys(kept))
    return kept + [k for k in MENU_KEYS if k not in kept]


async def menu_order(session: AsyncSession) -> list[str]:
    return _normalize(await get_value(session, SETTING_KEY))


def _labels(order: list[str]) -> str:
    return " › ".join(MENU_LABELS[k] for k in order)


async def save_order(
    session: AsyncSession, actor: AuditActor, order: list[str] | None
) -> list[str]:
    """Lưu thứ tự (commit); ``None`` ⇒ về mặc định (xóa dòng). Phải đủ mọi mục, không trùng."""
    if order is not None and sorted(order) != sorted(MENU_KEYS):
        raise AppError("E-MENU-1", "Thứ tự menu phải gồm đủ mọi mục, mỗi mục một lần.", 422)
    before = await menu_order(session)
    if order is None:
        await session.execute(delete(AppSetting).where(AppSetting.key == SETTING_KEY))
    else:
        stmt = insert(AppSetting).values(key=SETTING_KEY, value=order, updated_by_label=actor.label)
        await session.execute(
            stmt.on_conflict_do_update(
                index_elements=[AppSetting.key],
                set_={"value": stmt.excluded.value, "updated_by_label": actor.label},
            )
        )
    after = order or list(MENU_KEYS)
    if after != before:
        change = audit_change("Thứ tự menu", _labels(before), _labels(after))
        audit(
            session,
            actor,
            "settings.menu_order",
            "setting",
            SETTING_KEY,
            audit_detail(None, "Menu khu quản trị", [change], reset=order is None),
        )
    await session.commit()
    return after


# ---------------------------------------------------------------- router (chỉ Admin)

router = APIRouter(
    prefix="/admin/menu-order", tags=["admin: menu"], dependencies=[Depends(require_origin)]
)
MenuManager = Annotated[Principal, Depends(require(Perm.SETTINGS_MENU))]


@router.put("", response_model=MenuOrderOut)
async def put_menu_order(data: MenuOrderIn, p: MenuManager, session: SessionDep):
    """Lưu thứ tự chung. Thiếu / trùng mục ⇒ 422 E-MENU-1; key lạ ⇒ 422."""
    return MenuOrderOut(order=await save_order(session, p.audit_actor, list(data.order)))


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def reset_menu_order(p: MenuManager, session: SessionDep):
    """Về mặc định (xóa thứ tự đã lưu)."""
    await save_order(session, p.audit_actor, None)
