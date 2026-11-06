"""Khu hội viên trên web (T-016 đợt 1, ADR-009) – "Hồ sơ của tôi" + ảnh đại diện.

BFF ghép Xác thực (liên kết tài khoản, đồng bộ Họ tên) + Hội viên (hồ sơ, ảnh). Mọi API lấy hồ sơ
**theo phiên** (``CurrentMember``), không theo tham số trên URL (SEC1). Ghi cần Origin.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, Path, Response, UploadFile, status
from fastapi.responses import Response as RawResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import images
from app.core.audit import AuditActor
from app.core.config import settings
from app.core.db import SessionDep
from app.core.middleware import require_origin
from app.core.ratelimit import rate_limit
from app.modules.auth import api as auth
from app.modules.member_area.schemas import AvatarOut, MemberMeIn, MemberMeOut
from app.modules.members import api as members
from app.modules.records import api as records

router = APIRouter(prefix="/member-area", tags=["member-area"])


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def avatar_url(customer_id: int, etag: str | None) -> str | None:
    if etag is None:
        return None
    return f"{settings.API_PREFIX}/member-area/avatars/{customer_id}?v={etag}"


def short_name(full_name: str) -> str:
    words = full_name.split()
    return words[-1] if words else full_name


def to_out(p: members.SelfProfile, record_kmh: int | None = None) -> MemberMeOut:
    return MemberMeOut(
        member_code=p.member_code,
        full_name=p.full_name,
        short_name=short_name(p.full_name),
        nickname=p.nickname,
        email=p.email,
        phone=p.phone,
        joined_at=p.joined_at.astimezone(settings.tz).date(),
        tier=p.tier,
        racket=p.racket,
        show_on_records=p.show_on_records,
        avatar_url=avatar_url(p.customer_id, p.avatar_etag),
        record_kmh=record_kmh,
        version=p.version,
    )


async def _profile(session: AsyncSession, member: auth.LinkedMember) -> members.SelfProfile:
    profile = await members.get_self_profile(session, member.customer_id)
    if profile is None:  # liên kết trỏ tới hồ sơ không còn là hội viên – phòng hờ
        raise members.not_member()
    return profile


def _actor(member: auth.LinkedMember, member_code: str) -> AuditActor:
    return AuditActor(
        type="customer", id=member.user_id, label=f"Hội viên (tự sửa) · {member_code}"
    )


@router.get("/me", response_model=MemberMeOut, dependencies=[Depends(no_store)])
async def get_me(member: auth.CurrentMember, session: SessionDep):
    """Hồ sơ của tôi (mỗi lần mở đọc bản mới nhất). 401 E-AUTH-1 · 403 E-HV-8 (chưa là hội viên)."""
    profile = await _profile(session, member)
    return to_out(profile, await records.record_kmh(session, profile.customer_id))


@router.put(
    "/me",
    response_model=MemberMeOut,
    dependencies=[Depends(require_origin), Depends(no_store)],
)
async def update_me(data: MemberMeIn, member: auth.CurrentMember, session: SessionDep):
    """Lưu thay đổi: kiểm mọi ô một lần (422 ``fields``: full_name / nickname / email / tier /
    racket), 409 E-HV-12 (vừa được sửa ở nơi khác). Không đổi gì -> trả hồ sơ, không ghi.
    Hạng hội viên tự chọn (T-042); đổi hạng ghi audit ``member.tier_self_change``."""
    current = await _profile(session, member)
    profile, changed = await members.update_self_profile(
        session,
        member.customer_id,
        members.SelfUpdate(
            full_name=data.full_name,
            nickname=data.nickname,
            email=data.email,
            tier=data.tier,
            tier_sent="tier" in data.model_fields_set,
            racket=data.racket,
            show_on_records=data.show_on_records,
            version=data.version,
        ),
        _actor(member, current.member_code),
    )
    if changed:
        await auth.set_full_name(session, member.user_id, profile.full_name)
        await session.commit()
    return to_out(profile, await records.record_kmh(session, profile.customer_id))


@router.put(
    "/me/avatar",
    response_model=AvatarOut,
    dependencies=[
        Depends(require_origin),
        Depends(no_store),
        Depends(rate_limit("member.avatar", 20, key="user")),
    ],
)
async def upload_avatar(
    member: auth.CurrentMember,
    session: SessionDep,
    file: Annotated[UploadFile, File(description="JPG / PNG / WebP ≤ 5 MB")],
    crop_x: Annotated[int, Form(ge=0)],
    crop_y: Annotated[int, Form(ge=0)],
    crop_size: Annotated[int, Form(ge=1)],
):
    """Cắt vuông theo khung (pixel ảnh gốc, sau khi xoay theo EXIF), lưu ngay – không đổi
    ``version`` của form. 422 E-HV-13 (định dạng / dung lượng / vùng cắt)."""
    current = await _profile(session, member)
    data = await file.read(settings.AVATAR_MAX_BYTES + 1)
    stored = await members.save_avatar(
        session,
        member.customer_id,
        data,
        members.Crop(crop_x, crop_y, crop_size),
        _actor(member, current.member_code),
    )
    await session.commit()
    return AvatarOut(avatar_url=avatar_url(member.customer_id, stored.etag))


@router.delete(
    "/me/avatar",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_origin)],
)
async def delete_avatar(member: auth.CurrentMember, session: SessionDep):
    """Xóa ảnh -> về chữ cái. Chưa có ảnh -> vẫn 204."""
    current = await _profile(session, member)
    if await members.delete_avatar(
        session, member.customer_id, _actor(member, current.member_code)
    ):
        await session.commit()


@router.get(
    "/avatars/{customer_id}",
    response_class=RawResponse,
    responses={200: {"content": {"image/webp": {}}}, 304: {}, 404: {}},
)
async def get_avatar(
    customer_id: Annotated[int, Path(ge=1)],
    session: SessionDep,
    if_none_match: Annotated[str | None, Header()] = None,
    v: str | None = None,
):
    """Ảnh đại diện (công khai). ``v`` = etag để phá cache; trả cache 1 năm, ``nosniff``."""
    stored = await members.load_avatar(session, customer_id)
    return images.image_response(stored, if_none_match, images.CACHE_IMMUTABLE)
