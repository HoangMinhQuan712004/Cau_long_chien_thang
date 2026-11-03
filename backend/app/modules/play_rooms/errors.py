"""Lỗi phòng chơi (T-017) – câu tiếng Việt cho người dùng cuối."""

from app.core.errors import AppError


def not_found() -> AppError:
    """Không có / Host chưa đủ điều kiện (ẩn, AC2) / không phải của mình."""
    return AppError("E-NOT-FOUND", "Không tìm thấy phòng.", 404)


def closed() -> AppError:
    return AppError("E-ROOM-1", "Phòng đã đóng.", 409)


def full() -> AppError:
    return AppError("E-ROOM-2", "Phòng đã đủ 8 người.", 409)


def no_member_account() -> AppError:
    """Một câu cho mọi lý do (không có hội viên / chưa liên kết / Ngừng) – không dò được (SEC2)."""
    return AppError("E-ROOM-3", "Số điện thoại này chưa có tài khoản hội viên.", 422)


def already_in_room() -> AppError:
    return AppError("E-ROOM-4", "Người này đã ở trong phòng.", 409)


def in_match(no: int, me: bool) -> AppError:
    if me:
        message = f"Bạn đang trong trận #{no}. Kết thúc trận trước khi rời phòng."
    else:
        message = f"Người này đang trong trận #{no}. Kết thúc trận trước khi mời ra."
    return AppError("E-ROOM-5", message, 409, match_no=no)


def stale() -> AppError:
    return AppError("E-ROOM-6", "Phòng vừa thay đổi, đã tải lại.", 409)


def host_only() -> AppError:
    return AppError("E-ROOM-7", "Chỉ Host được làm thao tác này.", 403)


def bad_lineup() -> AppError:
    """Đội hình Host xếp tay (T-027): người không ở phòng, trùng người, sai số người."""
    return AppError("E-ROOM-12", "Đội hình không hợp lệ.", 422)


def tier_blocked(range_text: str, unranked: bool) -> AppError:
    """Ngoài khoảng hạng của phòng (T-031) – không nói hạng của người được mời."""
    message = f"Phòng chỉ dành cho hạng {range_text}."
    if unranked:
        message += " Liên hệ quầy để được xếp hạng."
    return AppError("E-ROOM-13", message, 409)


def bad_tier_range() -> AppError:
    return AppError("E-ROOM-14", "Khoảng hạng không hợp lệ.", 422)


def not_enough_players() -> AppError:
    return AppError("E-ROOM-8", "Chưa đủ người để bốc.", 409)


def bad_score() -> AppError:
    return AppError("E-ROOM-9", "Tỉ số không hợp lệ (0–99, không hòa).", 422)


def too_early() -> AppError:
    return AppError("E-ROOM-10", "Chưa tới giờ bắt đầu trận.", 409)


def match_in_progress(no: int) -> AppError:
    """Đang có trận chưa kết thúc: không bốc / đổi thể thức (mỗi phòng 1 trận đang chơi)."""
    return AppError("E-ROOM-11", f"Trận #{no} đang diễn ra. Kết thúc trận trước.", 409, match_no=no)
