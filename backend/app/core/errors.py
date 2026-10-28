from fastapi import HTTPException, status


class NotFound(HTTPException):
    def __init__(self, detail: str | dict[str, str] = "Không tìm thấy"):
        super().__init__(status.HTTP_404_NOT_FOUND, detail)


class BadRequest(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status.HTTP_400_BAD_REQUEST, detail)


class Conflict(HTTPException):
    # dict khi FE cần mã lỗi: {code, message}
    def __init__(self, detail: str | dict[str, str]):
        super().__init__(status.HTTP_409_CONFLICT, detail)


class Unauthorized(HTTPException):
    def __init__(self, detail: str = "Chưa đăng nhập"):
        super().__init__(status.HTTP_401_UNAUTHORIZED, detail)


class Forbidden(HTTPException):
    def __init__(self, detail: str = "Không có quyền"):
        super().__init__(status.HTTP_403_FORBIDDEN, detail)


def coded_error(
    code: str,
    status_code: int,
    message: str,
    *,
    retry_after: int | None = None,
    attempts_left: int | None = None,
) -> HTTPException:
    """`detail: {code, message, retry_after?, attempts_left?}` (+ header Retry-After)."""
    detail: dict[str, str | int] = {"code": code, "message": message}
    headers = None
    if retry_after is not None:
        detail["retry_after"] = retry_after
        headers = {"Retry-After": str(retry_after)}
    if attempts_left is not None:
        detail["attempts_left"] = attempts_left
    return HTTPException(status_code, detail, headers=headers)
