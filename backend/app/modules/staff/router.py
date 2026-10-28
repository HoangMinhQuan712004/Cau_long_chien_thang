from fastapi import APIRouter, status

from app.modules.auth.deps import AdminUser, SessionDep
from app.modules.staff import service
from app.modules.staff.schemas import (
    StaffCreateIn,
    StaffOut,
    StaffPasswordIn,
    StaffSessionOut,
    StaffUpdateIn,
)

# Chỉ chủ sân; id không phải nhân viên ⇒ 404
router = APIRouter(prefix="/admin/staff", tags=["admin: staff"])


@router.get("", response_model=list[StaffOut])
async def list_staff(_: AdminUser, session: SessionDep):
    return await service.list_staff(session)


@router.post(
    "",
    response_model=StaffOut,
    status_code=status.HTTP_201_CREATED,
)
async def create_staff(data: StaffCreateIn, admin: AdminUser, session: SessionDep):
    return await service.create_staff(session, admin, data)


@router.patch("/{staff_id}", response_model=StaffOut)
async def update_staff(staff_id: int, data: StaffUpdateIn, admin: AdminUser, session: SessionDep):
    return await service.update_staff(session, admin, staff_id, data)


@router.post("/{staff_id}/password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_staff_password(
    staff_id: int, data: StaffPasswordIn, admin: AdminUser, session: SessionDep
):
    await service.reset_staff_password(session, admin, staff_id, data.password)


@router.get("/{staff_id}/sessions", response_model=list[StaffSessionOut])
async def list_staff_sessions(staff_id: int, _: AdminUser, session: SessionDep):
    return await service.list_staff_sessions(session, staff_id)


@router.delete("/{staff_id}/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_staff_session(
    staff_id: int, session_id: int, admin: AdminUser, session: SessionDep
):
    await service.revoke_staff_session(session, admin, staff_id, session_id)
