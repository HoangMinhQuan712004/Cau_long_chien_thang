from datetime import date, datetime
from enum import IntEnum
from typing import Literal

from pydantic import BaseModel

from app.core.audit import Value

ActorKind = Literal["admin", "staff", "system", "customer"]
AuditSort = Literal["at_desc", "at_asc"]


# IntEnum vì query là chuỗi: Literal[20, 50, 100] không nhận "20"
class AuditPageSize(IntEnum):
    """Số dòng / trang: 20 | 50 | 100."""

    S20 = 20
    S50 = 50
    S100 = 100


PAGE_SIZE = AuditPageSize.S50  # BR-015


class AuditTargetOut(BaseModel):
    code: str | None
    name: str | None


class AuditChangeOut(BaseModel):
    field: str
    before: Value  # None = "(trống)" khi tạo mới
    after: Value


class AuditEntryOut(BaseModel):
    id: int
    at: datetime
    actor: ActorKind
    actor_label: str  # Admin / Nhân viên / Hệ thống
    actor_name: str | None  # Nhân viên: tên lúc làm (BR-008); Hội viên: nhãn "… · HV0031"
    actor_code: str | None  # chỉ Nhân viên: mã NV hiện tại (khóa link); không tìm được NV -> null
    action: str  # mã loại trong danh mục
    action_label: str
    target: AuditTargetOut
    changes: list[AuditChangeOut]  # rỗng = không có giá trị trước/sau ("—")


class AuditLogPageOut(BaseModel):
    items: list[AuditEntryOut]
    total: int
    page: int
    page_size: int
    date_from: date
    date_to: date


class AuditOptionOut(BaseModel):
    key: str
    label: str


class AuditGroupOut(BaseModel):
    label: str
    types: list[AuditOptionOut]


class AuditCatalogOut(BaseModel):
    groups: list[AuditGroupOut]
    actors: list[AuditOptionOut]
    min_date: date  # chọn được từ ngày này (12 tháng gần nhất)
    max_date: date  # tới hôm nay


class AuditLogQuery(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    actor: ActorKind | None = None
    action: str | None = None
    sort: AuditSort | None = None
    page: int = 1
    size: AuditPageSize = PAGE_SIZE
