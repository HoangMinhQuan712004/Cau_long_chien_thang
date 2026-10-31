from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.core.audit import AuditActor
from app.core.db import SessionDep
from app.core.idempotency import IdempotencyDep
from app.core.permissions import Perm, Principal, require
from app.core.ratelimit import rate_limit
from app.modules.members import api, listing, manage, profiles
from app.modules.members.schemas import (
    MemberCan,
    MemberCreateIn,
    MemberDetail,
    MemberListOut,
    MemberRow,
    MemberSearchItem,
    MemberUpdateIn,
    NextCodeOut,
    TempCreateIn,
    Tier,
)

router = APIRouter(prefix="/members", tags=["members"])

MemberSearcher = Annotated[Principal, Depends(require(Perm.MEMBER_SEARCH))]
MemberManager = Annotated[Principal, Depends(require(Perm.MEMBER_MANAGE))]


def _actor(p: Principal) -> AuditActor:
    return AuditActor(type=p.actor_type, id=p.actor_id, label=p.label)


def _can(p: Principal) -> MemberCan:
    return MemberCan(
        edit_status=p.has(Perm.MEMBER_STATUS), manage_rackets=p.has(Perm.RACKET_MANAGE)
    )


@router.get(
    "/search",
    response_model=list[MemberSearchItem],
    dependencies=[Depends(rate_limit("members.search", 60, key="user"))],
)
async def search_members(
    _: MemberSearcher,
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=50)],
):
    """Tìm hội viên theo mã / tên / SĐT (≥ 3 chữ số) – tối đa 20 dòng, SĐT đầy đủ."""
    return await api.search_members(session, q)


@router.get("", response_model=MemberListOut)
async def list_members(
    principal: MemberManager,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=50)] = None,
    kind: Literal["member", "temp"] | None = None,
    status_: Annotated[Literal["active", "inactive"] | None, Query(alias="status")] = None,
    tier: Annotated[
        Tier | Literal["none"] | None, Query(description="none = chưa xếp hạng")
    ] = None,
    racket: Annotated[
        str | None, Query(max_length=100, description="Tên vợt (không phân biệt hoa thường)")
    ] = None,
    sort: Annotated[
        Literal["bookings", "bookings_desc", "bookings_asc"] | None,
        Query(description="Số lần đặt: bookings = bookings_desc (nhiều trước) | bookings_asc"),
    ] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    """Hội viên + hồ sơ tạm: lọc (q, kind, status, tier, racket), phân trang, đếm theo loại.

    SĐT đầy đủ, không lộ id. ``counts`` áp mọi bộ lọc trừ ``kind``.
    """
    return await listing.list_members(
        session,
        _can(principal),
        q=q,
        kind=kind,
        status=status_,
        tier=tier,
        racket=racket,
        sort=sort,
        page=page,
        size=size,
    )


@router.get("/next-code", response_model=NextCodeOut)
async def next_code(_: MemberManager, session: SessionDep):
    """Mã HV tiếp theo – chỉ hiển thị trong ô khóa; mã thật cấp lúc lưu. 409 E-MEM-4 (hết mã)."""
    return NextCodeOut(member_code=await profiles.next_code(session))


@router.post("", response_model=MemberRow, status_code=status.HTTP_201_CREATED)
async def create_member(
    data: MemberCreateIn, principal: MemberManager, idem: IdempotencyDep, session: SessionDep
):
    """Thêm hội viên. Cần ``Idempotency-Key``: gửi lại cùng key -> trả đúng kết quả cũ (201 cùng
    mã HV, không báo trùng SĐT với chính hồ sơ vừa tạo – T-020 AC3).

    Lỗi: E-001/E-002 · 409 E-018 (SĐT của hội viên) · 409 E-MEM-1 "Số điện thoại đã có hồ sơ
    tạm: {Họ tên} (tạo dd/mm/yyyy)" (SRS E-004 – không nâng hồ sơ tạm, T-020 AC1).
    """

    async def run() -> MemberRow:
        return await manage.create_member(session, _actor(principal), data)

    return await idem.run(session, principal.key, run, status_code=status.HTTP_201_CREATED)


@router.post("/temp", response_model=MemberRow, status_code=status.HTTP_201_CREATED)
async def create_temp(
    data: TempCreateIn, principal: MemberManager, idem: IdempotencyDep, session: SessionDep
):
    """Tạo hồ sơ tạm. Cần ``Idempotency-Key`` (gửi lại -> kết quả cũ, T-020 AC3).

    Lỗi: E-001/E-002 · 409 E-018 / E-MEM-1 (đã có hồ sơ tạm).
    """

    async def run() -> MemberRow:
        return await manage.create_temp(session, _actor(principal), data)

    return await idem.run(session, principal.key, run, status_code=status.HTTP_201_CREATED)


@router.get("/{ref}", response_model=MemberDetail)
async def get_member(ref: str, principal: MemberManager, session: SessionDep):
    """Chi tiết, số lượt, tổng phút, 5 lượt gần nhất (ghi nhật ký). 404 E-NOT-FOUND."""
    return await listing.get_detail(session, _actor(principal), ref, _can(principal))


@router.patch("/{ref}", response_model=MemberRow)
async def update_member(
    ref: str, data: MemberUpdateIn, principal: MemberManager, session: SessionDep
):
    """Sửa hội viên (mã HV) hoặc hồ sơ tạm (``ref``; chỉ họ tên, giới tính – khác ⇒ 422 E-MEM-6).

    Gửi kèm ``version`` (từ danh sách / chi tiết): lệch -> 409 E-MEM-9 (máy khác hoặc hội viên tự
    sửa ở khu hội viên vừa lưu – T-020 AC4). 403 E-AUTH-2: NV đổi trạng thái. 404 E-NOT-FOUND.
    """
    return await manage.update_profile(session, _actor(principal), ref, data, _can(principal))
