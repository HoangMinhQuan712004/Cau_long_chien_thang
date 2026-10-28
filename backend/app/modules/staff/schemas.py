from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.modules.auth.schemas import NewPassword


class StaffCreateIn(BaseModel):
    """Tạo nhân viên; mã + tên đăng nhập do hệ thống sinh, trường lạ bị bỏ qua."""

    full_name: str = Field(min_length=1, max_length=255)
    password: NewPassword


class StaffUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    is_active: bool | None = None


class StaffPasswordIn(BaseModel):
    password: NewPassword


class StaffOut(BaseModel):
    id: int
    staff_code: str  # NV007
    full_name: str
    username: str  # tự sinh lúc tạo, vd an.nv007
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None
    active_sessions: int


class StaffSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
    expires_at: datetime
    user_agent: str | None
    ip: str | None
