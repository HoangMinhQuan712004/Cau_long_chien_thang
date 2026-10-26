from typing import Any

from fastapi import HTTPException, status


class AppError(HTTPException):
    """Lỗi chuẩn (ADR-004 §4): ``{"detail": {"code": "E-003", "message": "…", …}}``.

    FE map theo ``code``, không phụ thuộc câu chữ. ``extra`` thêm trường phụ vào ``detail``
    (vd. ``items`` – danh sách khung vướng).
    """

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        headers: dict[str, str] | None = None,
        **extra: Any,
    ):
        self.code = code
        self.message = message
        super().__init__(status_code, {"code": code, "message": message, **extra}, headers)


# --- Lỗi kiểu cũ (detail là chuỗi) – giữ tương thích cho API cũ ---


class NotFound(HTTPException):
    def __init__(self, detail: str = "Không tìm thấy"):
        super().__init__(status.HTTP_404_NOT_FOUND, detail)


class BadRequest(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status.HTTP_400_BAD_REQUEST, detail)


class Conflict(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status.HTTP_409_CONFLICT, detail)


class Unauthorized(HTTPException):
    def __init__(self, detail: str = "Chưa đăng nhập"):
        super().__init__(status.HTTP_401_UNAUTHORIZED, detail)


class Forbidden(HTTPException):
    def __init__(self, detail: str = "Không có quyền"):
        super().__init__(status.HTTP_403_FORBIDDEN, detail)
