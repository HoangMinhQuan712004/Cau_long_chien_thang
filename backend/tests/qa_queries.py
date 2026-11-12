# ruff: noqa: E501
"""Helper của QA (không phải test): đếm số câu SQL một đoạn mã chạy.

T-067 AC3: test không được quyết đúng / sai theo số đo thời gian tuyệt đối (ms) vì kết quả đổi theo tải máy
CI, băm rẻ, đồng hồ... Ý "đủ nhanh dù dữ liệu lớn" được kiểm bằng điều kiện xác định: số câu SQL một yêu cầu
không phụ thuộc số dòng dữ liệu (không N+1) và bị chặn trên bởi một hằng số.
"""

from contextlib import contextmanager

from sqlalchemy import event

from app.core.db import engine


@contextmanager
def count_statements():
    """``with count_statements() as n: ...`` – ``n[0]`` là số câu SQL đã gửi lên DB trong khối."""
    counter = [0]

    def before(conn, cursor, statement, parameters, context, executemany):
        counter[0] += 1

    event.listen(engine.sync_engine, "before_cursor_execute", before)
    try:
        yield counter
    finally:
        event.remove(engine.sync_engine, "before_cursor_execute", before)
