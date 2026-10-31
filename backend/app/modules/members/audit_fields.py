"""Nội dung dòng Lịch sử thao tác của hồ sơ khách (SRS Lịch sử thao tác BR-006, BR-007, BR-008)."""

from typing import Any

from app.core.audit import Value, audit_changes, audit_detail
from app.modules.members.models import Customer

GENDERS = {"male": "Nam", "female": "Nữ"}

# Tên ô theo thứ tự hiện trên màn; SĐT ghi đầy đủ (BR-007)
MEMBER_LABELS = {
    "kind": "Loại hồ sơ",
    "full_name": "Họ tên",
    "phone": "SĐT",
    "gender": "Giới tính",
    "tier": "Trình độ",
    "racket": "Vợt đang dùng",
    "is_active": "Trạng thái",
}
TEMP_LABELS = {k: MEMBER_LABELS[k] for k in ("full_name", "phone", "gender")}


def snapshot(c: Customer) -> dict[str, Value]:
    """Giá trị hiển thị lúc làm (chụp lại, không tra theo mã khi xem)."""
    return {
        "kind": "Hội viên" if c.kind == "member" else "Hồ sơ tạm",
        "full_name": c.full_name,
        "phone": c.phone,
        "gender": GENDERS.get(c.gender or ""),
        "tier": c.tier,
        "racket": c.racket,
        "is_active": "Hoạt động" if c.is_active else "Ngừng",
    }


def member_detail(
    c: Customer, before: dict[str, Value] | None = None, **extra: Any
) -> dict[str, Any]:
    """Thêm / sửa / nâng hội viên: đối tượng Mã HV + họ tên; ``before`` None = tạo mới."""
    labels = MEMBER_LABELS if before else {k: v for k, v in MEMBER_LABELS.items() if k != "kind"}
    changes = audit_changes(labels, before or {}, snapshot(c))
    return audit_detail(c.member_code, c.full_name, changes, **extra)


def temp_detail(full_name: str, phone: str, gender: str | None = None) -> dict[str, Any]:
    """Tạo hồ sơ tạm: đối tượng họ tên + SĐT, "(trống) → họ tên, SĐT"."""
    after = {"full_name": full_name, "phone": phone, "gender": GENDERS.get(gender or "")}
    return audit_detail(None, f"{full_name} · {phone}", audit_changes(TEMP_LABELS, {}, after))
