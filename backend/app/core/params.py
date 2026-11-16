"""Tham số đường dẫn là id số (T-070).

Id ngoài khoảng của cột (``BIGINT``: 1 … 2^63−1) trước đây tới tận Postgres -> asyncpg lỗi tràn số
-> 500; id 0 / âm thì 422. Giờ ngoài khoảng -> **404 giống bản ghi không tồn tại** (lỗi của từng
module), không 422: không lộ khác biệt giữa "không có" và "không hợp lệ" (T-054, SEC6).

Dùng: ``RoomId = path_id("room_id", errors.not_found)`` rồi ``room_id: RoomId`` trong route. Kiểm
trong dependency nên chạy trước kiểm body -> id sai luôn 404, kể cả khi body cũng sai.
"""

from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, Path

from app.core.errors import AppError

BIGINT_MAX = 2**63 - 1
SMALLINT_MAX = 2**15 - 1


def not_found(message: str) -> Callable[[], AppError]:
    """404 ``E-NOT-FOUND`` với câu cho người dùng – cho module chưa có hàm lỗi riêng."""
    return lambda: AppError("E-NOT-FOUND", message, 404)


def path_id(
    name: str,
    not_found: Callable[[], Exception],
    *,
    max_value: int = BIGINT_MAX,
    description: str | None = None,
) -> Any:
    """Kiểu ``Annotated[int, Depends(...)]`` cho path param ``name``: ngoài ``1 … max_value`` ->
    ``raise not_found()``."""

    def check(value: Annotated[int, Path(alias=name, description=description)]) -> int:
        if not 1 <= value <= max_value:
            raise not_found()
        return value

    check.__name__ = f"path_{name}"
    return Annotated[int, Depends(check)]
