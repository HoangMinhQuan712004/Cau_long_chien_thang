"""Lịch sử thao tác – chỉ Admin (SRS Lịch sử thao tác BR-001). Không có API sửa / xóa (BR-010)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.core.db import SessionDep
from app.core.permissions import Perm, Principal, require
from app.modules.audit_log import service
from app.modules.audit_log.schemas import (
    PAGE_SIZE,
    ActorKind,
    AuditCatalogOut,
    AuditLogPageOut,
    AuditLogQuery,
    AuditPageSize,
    AuditSort,
)

router = APIRouter(prefix="/admin/audit-log", tags=["admin: audit log"])

AuditViewer = Annotated[Principal, Depends(require(Perm.AUDIT_LOG_VIEW))]


@router.get("/catalog", response_model=AuditCatalogOut)
async def get_catalog(_: AuditViewer):
    """Danh mục cho bộ lọc: loại thao tác theo nhóm, người làm, khoảng ngày chọn được."""
    return service.get_catalog()


@router.get("", response_model=AuditLogPageOut)
async def list_audit_log(
    _: AuditViewer,
    session: SessionDep,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    actor: Annotated[ActorKind | None, Query()] = None,
    action: Annotated[str | None, Query(max_length=60)] = None,
    sort: Annotated[
        AuditSort | None,
        Query(description="Thời điểm: at_desc (mặc định, mới trước) | at_asc (cũ trước)"),
    ] = None,
    page: Annotated[int, Query(ge=1, le=10_000)] = 1,
    size: Annotated[
        AuditPageSize, Query(description="Số dòng / trang: 20 | 50 (mặc định) | 100")
    ] = PAGE_SIZE,
):
    """Lịch sử thao tác: mặc định 7 ngày gần nhất, 50 dòng / trang, mới nhất trước.

    Lỗi: E-AUDIT-1 (khoảng ngày sai / ngoài 12 tháng), E-AUDIT-2 (loại thao tác không có).
    """
    return await service.list_entries(
        session,
        AuditLogQuery(
            date_from=date_from,
            date_to=date_to,
            actor=actor,
            action=action,
            sort=sort,
            page=page,
            size=size,
        ),
    )
