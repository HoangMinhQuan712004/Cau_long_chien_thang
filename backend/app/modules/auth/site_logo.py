"""Logo web: Admin đổi / xóa (``/admin/site/logo``); ai cũng xem được (``/site/logo``, ``favicon``).

Lưu ở bảng ``site_logo`` (một dòng); chưa có logo -> link null, FE hiện icon mặc định.
"""

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core import images
from app.core.audit import AuditActor, audit, audit_change, audit_detail
from app.core.config import settings
from app.core.middleware import require_origin
from app.core.permissions import Perm, Principal, require
from app.core.ratelimit import rate_limit
from app.core.settings_store import SiteLogo
from app.modules.auth.deps import SessionDep

CACHE_TAG = "site-branding"  # trang khách dùng "use cache": đổi logo xong FE xóa cache tag này
LOGO_ROW_ID = 1
# Không có ``?v=`` đúng etag -> link cố định: logo đổi là phải thấy
CACHE_SHORT = "public, max-age=300"


class SiteLogoUrls(BaseModel):
    logo_url: str | None = Field(description="Đã gồm ?v={etag}; null -> FE hiện icon mặc định")
    favicon_url: str | None = Field(description="PNG nhỏ, đã gồm ?v={etag}; null khi chưa có logo")


class SiteBrandingSavedOut(SiteLogoUrls):
    cache_tag: str = Field(description="Tag FE cần xóa (revalidateTag) để trang khách thấy logo")


def logo_urls(etag: str | None) -> dict[str, str | None]:
    if etag is None:
        return {"logo_url": None, "favicon_url": None}
    prefix = f"{settings.API_PREFIX}/site"
    return {"logo_url": f"{prefix}/logo?v={etag}", "favicon_url": f"{prefix}/favicon?v={etag}"}


def _saved(etag: str | None) -> SiteBrandingSavedOut:
    return SiteBrandingSavedOut(**logo_urls(etag), cache_tag=CACHE_TAG)


async def save_logo(
    session: AsyncSession, actor: AuditActor, data: bytes, crop: images.Crop
) -> str:
    """Ghi đè logo (commit), trả etag. Ảnh lỗi -> 422 ``E-HV-13`` (cùng mã + câu với avatar)."""
    webp, favicon = await asyncio.to_thread(images.process_logo, data, crop)
    etag = images.etag_of(webp)
    had_logo = await session.scalar(select(SiteLogo.etag)) is not None
    values = {
        "content_type": images.CONTENT_TYPE,
        "bytes": webp,
        "favicon_bytes": favicon,
        "etag": etag,
        "updated_by_label": actor.label,
    }
    await session.execute(
        insert(SiteLogo)
        .values(id=LOGO_ROW_ID, **values)
        .on_conflict_do_update(
            index_elements=[SiteLogo.id], set_={**values, "updated_at": func.now()}
        )
    )
    change = audit_change("Logo", "Có ảnh" if had_logo else None, "Ảnh mới")
    detail = audit_detail(None, "Logo web", [change])
    audit(session, actor, "settings.logo_update", "setting", "site_logo", detail)
    await session.commit()
    return etag


async def delete_logo(session: AsyncSession, actor: AuditActor) -> None:
    """Xóa logo -> về icon mặc định; chưa có logo -> không làm gì, không ghi nhật ký."""
    result = await session.execute(delete(SiteLogo))
    if result.rowcount:
        change = audit_change("Logo", "Có ảnh", None)
        detail = audit_detail(None, "Logo web", [change])
        audit(session, actor, "settings.logo_delete", "setting", "site_logo", detail)
    await session.commit()


# ---------------------------------------------------------------- Admin

admin_router = APIRouter(prefix="/admin/site", tags=["admin: site"])
SiteManager = Annotated[Principal, Depends(require(Perm.SETTINGS_SITE))]
_WRITE_GUARDS = [Depends(require_origin), Depends(rate_limit("site.logo", 20, key="user"))]


@admin_router.put("/logo", response_model=SiteBrandingSavedOut, dependencies=_WRITE_GUARDS)
async def upload_logo(
    p: SiteManager,
    session: SessionDep,
    file: Annotated[UploadFile, File(description="JPG / PNG / WebP ≤ 5 MB; không nhận SVG")],
    crop_x: Annotated[int, Form(ge=0)],
    crop_y: Annotated[int, Form(ge=0)],
    crop_size: Annotated[int, Form(ge=1)],
):
    """Đổi logo (chỉ Admin): cắt vuông theo khung, giữ nền trong suốt, sinh kèm favicon PNG.

    422 / 413 E-HV-13 (định dạng / dung lượng / vùng cắt) · 429 E-SEC-5.
    """
    data = await file.read(settings.AVATAR_MAX_BYTES + 1)
    crop = images.Crop(crop_x, crop_y, crop_size)
    return _saved(await save_logo(session, p.audit_actor, data, crop))


@admin_router.delete("/logo", response_model=SiteBrandingSavedOut, dependencies=_WRITE_GUARDS)
async def remove_logo(p: SiteManager, session: SessionDep):
    """Xóa logo (chỉ Admin) -> về icon mặc định. Chưa có logo -> vẫn 200."""
    await delete_logo(session, p.audit_actor)
    return _saved(None)


# ---------------------------------------------------------------- công khai

public_router = APIRouter(prefix="/site", tags=["site"])
_IMAGE_RESPONSES = {200: {"content": {"image/*": {}}}, 304: {}, 404: {}}


async def _image(
    session: AsyncSession,
    column: InstrumentedAttribute[bytes],
    content_type: str,
    v: str | None,
    if_none_match: str | None,
) -> Response:
    row = (await session.execute(select(column, SiteLogo.etag))).first()
    stored = images.StoredImage(row[0], row[1], content_type) if row else None
    cache = images.CACHE_IMMUTABLE if stored and v == stored.etag else CACHE_SHORT
    return images.image_response(stored, if_none_match, cache)


@public_router.get("/logo", response_class=Response, responses=_IMAGE_RESPONSES)
async def site_logo(
    session: SessionDep,
    if_none_match: Annotated[str | None, Header()] = None,
    v: str | None = None,
):
    """Ảnh logo WebP (công khai). ``v`` = etag: đúng thì cache 1 năm, không thì cache ngắn."""
    return await _image(session, SiteLogo.bytes, images.CONTENT_TYPE, v, if_none_match)


@public_router.get("/favicon", response_class=Response, responses=_IMAGE_RESPONSES)
async def site_favicon(
    session: SessionDep,
    if_none_match: Annotated[str | None, Header()] = None,
    v: str | None = None,
):
    """Favicon PNG 64 px (công khai). ``v`` như ``/site/logo``."""
    return await _image(
        session, SiteLogo.favicon_bytes, images.FAVICON_CONTENT_TYPE, v, if_none_match
    )
