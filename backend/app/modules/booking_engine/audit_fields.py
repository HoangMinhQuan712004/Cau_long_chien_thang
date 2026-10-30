"""Giá trị hiển thị cho Lịch sử thao tác: sân, bảng giá, đặt sân (SRS Lịch sử thao tác BR-006)."""

from collections.abc import Sequence
from datetime import datetime

from app.core.audit import audit_change
from app.core.config import settings
from app.modules.booking_engine.dto import CustomerSnapshot
from app.modules.booking_engine.pricing import BAND_LABELS
from app.modules.booking_engine.schedules import Hours, to_hhmm

DAY_LABELS = {"weekday": "Ngày thường", "weekend": "Cuối tuần", "holiday": "Lễ/Tết"}

RESOURCE_LABELS = {
    "name": "Tên sân",
    "resource_type": "Loại sân",
    "open_time": "Giờ mở cửa",
    "close_time": "Giờ đóng cửa",
    "peak_bands": "Khung cao điểm",
    "is_active": "Trạng thái",
}


def vnd(amount: int | None) -> str | None:
    """120000 -> "120.000 ₫"."""
    return None if amount is None else f"{amount:,} ₫".replace(",", ".")


def active_label(is_active: bool) -> str:
    return "Đang dùng" if is_active else "Ngừng"


def bands_text(bands: Sequence[Sequence[str]]) -> str:
    """[["17:00", "22:00"]] -> "17:00–22:00"; không có khung -> "Không có"."""
    return ", ".join(f"{a}–{b}" for a, b in bands) or "Không có"


def hours_values(hours: Hours) -> dict[str, str]:
    return {
        "open_time": to_hhmm(hours.open_minute),
        "close_time": to_hhmm(hours.close_minute),
        "peak_bands": bands_text(hours.peak_bands_hhmm),
    }


def price_cell_label(type_name: str, day_type: str, band: str) -> str:
    """Tên ô bảng giá: "Sân thường · Cuối tuần · Cao điểm"."""
    return f"{type_name} · {DAY_LABELS.get(day_type, day_type)} · {BAND_LABELS.get(band, band)}"


def time_text(start_at: datetime, end_at: datetime) -> str:
    """Khung giờ theo giờ Việt Nam: "18:00–20:00 31/10/2026"."""
    tz = settings.tz
    start, end = start_at.astimezone(tz), end_at.astimezone(tz)
    return f"{start:%H:%M}–{end:%H:%M} {start:%d/%m/%Y}"


def customer_text(c: CustomerSnapshot) -> str:
    """Khách lúc đặt: "HV0031 · Nguyễn Văn An · 0901234567" (SĐT đầy đủ, BR-007)."""
    parts = [c.member_code] if c.kind == "member" and c.member_code else []
    return " · ".join([*parts, c.display_name, c.phone])


def paid_changes(method_label: str) -> list:
    """Thu tiền (quầy hoặc QR): "Thanh toán: Chưa thanh toán → Đã thanh toán" + phương thức."""
    return [
        audit_change("Thanh toán", "Chưa thanh toán", "Đã thanh toán"),
        audit_change("Phương thức", None, method_label),
    ]


def new_values(**fields: str | None) -> list:
    """Tạo mới: mỗi ô "(trống) → giá trị" theo thứ tự truyền vào (tên ô = khóa)."""
    return [audit_change(label, None, value) for label, value in fields.items() if value]
