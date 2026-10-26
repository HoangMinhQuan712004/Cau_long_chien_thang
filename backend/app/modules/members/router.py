from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.db import SessionDep
from app.core.permissions import Perm, Principal, require
from app.core.ratelimit import rate_limit
from app.modules.members import api
from app.modules.members.schemas import MemberSearchItem

router = APIRouter(prefix="/members", tags=["members"])

MemberSearcher = Annotated[Principal, Depends(require(Perm.MEMBER_SEARCH))]


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
    """Tìm hội viên theo mã / tên / SĐT (≥ 3 chữ số) – tối đa 20 dòng, SĐT đã che."""
    return await api.search_members(session, q)
