"""Danh mục vợt: NV + Admin đọc (ô "Vợt đang dùng"), chỉ Admin thêm / sửa / ẩn / xóa."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.core.audit import AuditActor
from app.core.db import SessionDep
from app.core.errors import AppError
from app.core.params import not_found, path_id
from app.core.permissions import OptionalPrincipal, Perm, Principal, require
from app.modules.auth import api as auth
from app.modules.auth.deps import unauthenticated
from app.modules.members import rackets
from app.modules.members.schemas import RacketCreateIn, RacketOut, RacketUpdateIn

router = APIRouter(prefix="/rackets", tags=["members"])
# Id ngoài khoảng cột -> 404 như không tồn tại (T-070)
RacketId = path_id("racket_id", not_found("Không tìm thấy vợt."))

RacketManager = Annotated[Principal, Depends(require(Perm.RACKET_MANAGE))]


def _actor(p: Principal) -> AuditActor:
    return AuditActor(type=p.actor_type, id=p.actor_id, label=p.label)


async def racket_reader(
    principal: OptionalPrincipal, member: auth.OptionalMember
) -> Principal | None:
    """NV / Admin (``MEMBER_MANAGE``) hoặc hội viên có hồ sơ (khu hội viên – T-016) -> None."""
    if principal is not None and principal.has(Perm.MEMBER_MANAGE):
        return principal
    if member is not None:
        return None
    if principal is None:
        raise unauthenticated()
    raise AppError("E-AUTH-2", "Không có quyền thực hiện thao tác này", 403)


@router.get("", response_model=list[RacketOut])
async def list_rackets(
    principal: Annotated[Principal | None, Depends(racket_reader)],
    session: SessionDep,
    all: bool = False,  # noqa: A002
):
    """Vợt đang dùng, theo thứ tự rồi tên. ``all=1`` (chỉ Admin) -> gồm cả vợt ẩn.

    Hội viên (khu hội viên) đọc được danh mục đang dùng."""
    include_hidden = all and principal is not None and principal.has(Perm.RACKET_MANAGE)
    return await rackets.list_rackets(session, include_hidden)


@router.post("", response_model=RacketOut, status_code=status.HTTP_201_CREATED)
async def create_racket(data: RacketCreateIn, principal: RacketManager, session: SessionDep):
    """Thêm vợt. 409 E-MEM-5 (trùng tên, không phân biệt hoa thường / khoảng trắng)."""
    return await rackets.create(session, _actor(principal), data)


@router.patch("/{racket_id}", response_model=RacketOut)
async def update_racket(
    racket_id: RacketId, data: RacketUpdateIn, principal: RacketManager, session: SessionDep
):
    """Sửa tên / ẩn-hiện / thứ tự. 404 E-NOT-FOUND · 409 E-MEM-5."""
    return await rackets.update(session, _actor(principal), racket_id, data)


@router.delete("/{racket_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_racket(racket_id: RacketId, principal: RacketManager, session: SessionDep):
    """Xóa hẳn (hồ sơ đang ghi vợt này giữ nguyên tên). 404 E-NOT-FOUND."""
    await rackets.delete(session, _actor(principal), racket_id)
