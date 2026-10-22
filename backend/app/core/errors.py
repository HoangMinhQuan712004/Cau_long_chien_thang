from fastapi import HTTPException, status


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
