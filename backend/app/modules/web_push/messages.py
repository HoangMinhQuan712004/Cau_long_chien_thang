"""Tiêu đề / câu chữ / đường dẫn push (T-076). Không SĐT, không tên người."""

from datetime import date, datetime

from app.core.config import settings
from app.modules.web_push.sender import Message

# ADR-015: chỉ các kind này của hộp thông báo hội viên được đẩy về máy
MEMBER_TITLES = {
    "booking.reminder": "Sắp đến giờ chơi",
    "booking.moved": "Buổi chơi đã được đổi",
    "booking.cancelled": "Buổi chơi đã bị hủy",
    "booking.paid": "Đã ghi nhận thanh toán",
    "room.join_requested": "Có người xin vào phòng",
    "room.join_approved": "Yêu cầu vào phòng được duyệt",
    "room.join_rejected": "Yêu cầu vào phòng bị từ chối",
}
PUSH_KINDS = frozenset(MEMBER_TITLES)
MEMBER_HISTORY = "/hoi-vien/lich-su-choi"
MEMBER_HOME = "/hoi-vien"

STAFF_ONLINE_BOOKING = "staff.online_booking"
STAFF_QR_RECEIVED = "staff.qr_received"
STAFF_MONEY_REVIEW = "staff.money_review"
STAFF_TITLES = {
    STAFF_ONLINE_BOOKING: "Đặt online mới",
    STAFF_QR_RECEIVED: "Đã nhận tiền QR",
    STAFF_MONEY_REVIEW: "Tiền về cần xử lý",
}
REVIEW_LABELS = {"partial": "Thiếu tiền", "refund_needed": "Cần hoàn", "unmatched": "Không khớp mã"}
MONEY_REVIEW_URL = "/admin/lich-su-giao-dich"


def member_url(kind: str, link: str | None) -> str:
    if link and link.startswith("/") and not link.startswith("//"):
        return link
    return MEMBER_HISTORY if kind.startswith("booking.") else MEMBER_HOME


def member_message(notification_id: int, kind: str, text: str, link: str | None) -> Message:
    return Message(
        title=MEMBER_TITLES[kind],
        body=text,
        url=member_url(kind, link),
        tag=f"{kind}:{notification_id}",
    )


def calendar_url(play_date: str | None) -> str:
    try:
        return f"/admin/dat-san?date={date.fromisoformat(play_date or '').isoformat()}"
    except ValueError:
        return "/admin/dat-san"


def vnd(amount: int) -> str:
    return f"{amount:,}".replace(",", ".") + " đ"


def _hm(moment: datetime) -> str:
    return f"{moment.hour}h" if moment.minute == 0 else f"{moment.hour}h{moment.minute:02d}"


def slot(start: str, end: str) -> tuple[str, str]:
    """(``18h–19h``, ``16/11``) theo giờ sân."""
    s = datetime.fromisoformat(start).astimezone(settings.tz)
    e = datetime.fromisoformat(end).astimezone(settings.tz)
    return f"{_hm(s)}–{_hm(e)}", f"{s:%d/%m}"


def online_booking_body(payload: dict) -> str:
    """``BK-… · Sân 1 18h–19h 16/11 · 200.000 đ`` (nhiều khung: ``(+n khung)``); vé:
    ``{sự kiện} · n vé · số tiền``."""
    amount = vnd(int(payload.get("amount") or 0))
    code = payload.get("order_code", "")
    if "session_name" in payload:
        seats = len(payload.get("codes") or [])
        return f"{payload['session_name']} · {seats} vé · {amount}"
    items = payload.get("items") or []
    if not items:
        return f"{code} · {amount}"
    hours, day = slot(items[0]["start_at"], items[0]["end_at"])
    first = f"{items[0]['resource_name']} {hours} {day}"
    more = f" (+{len(items) - 1} khung)" if len(items) > 1 else ""
    return f"{code} · {first}{more} · {amount}"
