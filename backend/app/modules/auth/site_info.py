"""Thông tin web: Admin sửa (``/admin/site/info``), trang khách đọc (``/site/branding``).

Lưu ở ``app_setting`` key ``site_info``; chưa lưu -> mặc định. Bản đồ: xem ``site_map``.
"""

import re
from dataclasses import asdict
from typing import Any

from email_validator import EmailNotValidError, validate_email
from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit, audit_change, audit_detail
from app.core.errors import AppError
from app.core.middleware import require_origin
from app.core.ratelimit import rate_limit
from app.core.schemas import StrictIn
from app.core.settings_store import AppSetting, SiteLogo, get_value
from app.modules.auth import site_map
from app.modules.auth.deps import SessionDep
from app.modules.auth.site_logo import CACHE_TAG, SiteLogoUrls, SiteManager, logo_urls

INFO_KEY = "site_info"
# Trường -> (nhãn nhật ký / lỗi, độ dài tối đa, mặc định khi Admin chưa lưu = theo ``lib/site.ts``)
INFO_FIELDS = {
    "name": ("Tên sân", 100, "Sân Cầu Lông ABC"),
    "address": ("Địa chỉ", 200, "123 Đường ABC, Phường XYZ, Quận Cầu Giấy, Hà Nội"),
    "phone": ("Hotline", 20, "0900 000 000"),
    "email": ("Email", 254, "lienhe@example.com"),
}
MAP_FIELDS = ("map_url", "lat", "lng")
# Hotline: chỉ di động 10 số (người dùng chốt); ``normalize_phone`` không kiểm đầu số
HOTLINE_RE = re.compile(r"0[35789]\d{8}")


class SiteMapOut(BaseModel):
    map_url: str | None = Field(description="Link Admin dán; null = chưa có bản đồ")
    lat: float | None = Field(description="Vĩ độ; cùng có hoặc cùng null với lng")
    lng: float | None = Field(description="Kinh độ")


class SiteInfoFields(SiteMapOut):
    name: str = Field(description="Tên sân, dùng chung cho mọi nơi hiển thị")
    address: str = Field(description="Một dòng")
    phone: str = Field(description="Hotline: số di động, đã tách 4-3-3 (0912 345 678)")
    email: str


class SiteBrandingOut(SiteLogoUrls, SiteInfoFields):
    """Dữ liệu công khai cho header, chân trang."""


class SiteInfoOut(SiteInfoFields):
    version: int = Field(description="Gửi lại khi lưu – khóa lạc quan; 0 = chưa lưu lần nào")


class SiteInfoSavedOut(SiteInfoOut):
    cache_tag: str = Field(description="Tag FE cần xóa (revalidateTag) để trang khách thấy mới")


class SiteInfoIn(StrictIn):
    """Độ dài, định dạng kiểm ở ``_clean_info``, bản đồ ở ``site_map`` (lỗi E-001 tiếng Việt)."""

    name: str = Field(max_length=1000)
    address: str = Field(max_length=1000)
    phone: str = Field(max_length=1000)
    email: str = Field(max_length=1000)
    map_url: str | None = Field(default=None, max_length=site_map.MAX_INPUT)
    lat: float | None = None
    lng: float | None = None
    version: int


class SiteMapResolveIn(StrictIn):
    input: str = Field(max_length=site_map.MAX_INPUT, description="Link Google Maps")


def _info_of(saved: Any) -> dict[str, Any]:
    """Các trường + ``version``; chưa lưu -> mặc định, không bản đồ, version 0."""
    stored = saved if isinstance(saved, dict) else {}
    fields = {k: stored.get(k) or spec[2] for k, spec in INFO_FIELDS.items()}
    map_fields = {k: stored.get(k) for k in MAP_FIELDS}
    return {**fields, **map_fields, "version": stored.get("version", 0)}


def _format_hotline(raw: str) -> str:
    """Bỏ khoảng trắng rồi tách 4-3-3: cùng số viết khác -> cùng một chuỗi."""
    digits = "".join(raw.split())
    if not (digits.isascii() and digits.isdigit()):
        raise AppError("E-001", "Hotline chỉ gồm chữ số.", 422)
    if not HOTLINE_RE.fullmatch(digits):
        raise AppError("E-001", "Hotline phải là số di động 10 số.", 422)
    return f"{digits[:4]} {digits[4:7]} {digits[7:]}"


def _clean_info(data: SiteInfoIn) -> dict[str, str]:
    """Gộp khoảng trắng (địa chỉ thành một dòng), kiểm bắt buộc + độ dài + định dạng."""
    clean = {k: " ".join(getattr(data, k).split()) for k in INFO_FIELDS}
    if clean["phone"]:
        clean["phone"] = _format_hotline(clean["phone"])
    for key, value in clean.items():
        label, limit, _ = INFO_FIELDS[key]
        if not value:
            raise AppError("E-001", f"Vui lòng nhập {label}.", 422)
        if len(value) > limit:
            raise AppError("E-001", f"{label} tối đa {limit} ký tự.", 422)
    try:
        clean["email"] = validate_email(clean["email"], check_deliverability=False).normalized
    except EmailNotValidError:
        raise AppError("E-001", "Email không hợp lệ.", 422) from None
    return clean


def _map_text(info: dict[str, Any]) -> str | None:
    if info["map_url"] is None:
        return None
    text = info["map_url"]
    return text if info["lat"] is None else f"{text} ({info['lat']}, {info['lng']})"


def _stale_info() -> AppError:
    return AppError("E-012", "Dữ liệu vừa được cập nhật ở máy khác. Vui lòng thử lại.", 409)


async def save_info(session: AsyncSession, actor: AuditActor, data: SiteInfoIn) -> dict[str, Any]:
    """Lưu thông tin web (commit). ``version`` cũ -> 409 E-012; không đổi gì -> không ghi."""
    clean: dict[str, Any] = _clean_info(data)
    clean.update(asdict(site_map.check_saved(data.map_url, data.lat, data.lng)))
    row = await session.scalar(
        select(AppSetting).where(AppSetting.key == INFO_KEY).with_for_update()
    )
    current = _info_of(row.value if row else None)
    if data.version != current["version"]:
        raise _stale_info()
    changes = [
        audit_change(INFO_FIELDS[k][0], current[k], clean[k])
        for k in INFO_FIELDS
        if clean[k] != current[k]
    ]
    if any(clean[k] != current[k] for k in MAP_FIELDS):
        changes.append(audit_change("Bản đồ", _map_text(current), _map_text(clean)))
    if not changes:
        return current
    value = {**clean, "version": current["version"] + 1}
    if row is not None:
        row.value = value
        row.updated_by_label = actor.label
    else:
        # Chưa có dòng để khóa: hai Admin lưu lần đầu cùng lúc -> UNIQUE key chặn người sau
        result = await session.execute(
            insert(AppSetting)
            .values(key=INFO_KEY, value=value, updated_by_label=actor.label)
            .on_conflict_do_nothing(index_elements=[AppSetting.key])
        )
        if not result.rowcount:
            raise _stale_info()
    detail = audit_detail(None, "Thông tin web", changes)
    audit(session, actor, "settings.site_info", "setting", INFO_KEY, detail)
    await session.commit()
    return value


admin_router = APIRouter(prefix="/admin/site", tags=["admin: site"])
public_router = APIRouter(prefix="/site", tags=["site"])


@admin_router.get("/info", response_model=SiteInfoOut)
async def get_site_info(_: SiteManager, session: SessionDep):
    """Thông tin web cho form Cài đặt (chỉ Admin), kèm ``version``."""
    return _info_of(await get_value(session, INFO_KEY))


@admin_router.put("/info", response_model=SiteInfoSavedOut, dependencies=[Depends(require_origin)])
async def put_site_info(data: SiteInfoIn, p: SiteManager, session: SessionDep):
    """Lưu thông tin web (chỉ Admin). 422 E-001 (thiếu / sai định dạng) · 409 E-012 (máy khác vừa
    lưu). Bỏ bản đồ: không gửi / null cả ``map_url``, ``lat``, ``lng``."""
    return {**await save_info(session, p.audit_actor, data), "cache_tag": CACHE_TAG}


@admin_router.post(
    "/map/resolve",
    response_model=SiteMapOut,
    dependencies=[Depends(require_origin), Depends(rate_limit("site.map", 20, key="user"))],
)
async def resolve_site_map(data: SiteMapResolveIn, _: SiteManager, session: SessionDep):
    """Đọc link Google Maps để xem trước, không ghi gì (chỉ Admin). Link không có tọa độ: giữ
    ``map_url``, ``lat`` / ``lng`` null.

    422 E-001: "Link Google Maps không hợp lệ." · "Chưa đọc được link, hãy thử lại." (Google lỗi).
    """
    # Ngoại lệ "gọi dịch vụ ngoài trong worker": Admin cần kết quả ngay, chỉ Admin, có rate limit +
    # timeout; trả kết nối DB (phiên đã kiểm quyền) trước khi gọi mạng để không giữ transaction
    await session.rollback()
    return asdict(await site_map.resolve(data.input))


@public_router.get("/branding", response_model=SiteBrandingOut)
async def site_branding(response: Response, session: SessionDep):
    """Thông tin web + link logo, favicon (null khi chưa có logo). Không cần đăng nhập."""
    response.headers["Cache-Control"] = "no-cache"
    info = _info_of(await get_value(session, INFO_KEY))
    return {**info, **logo_urls(await session.scalar(select(SiteLogo.etag)))}
