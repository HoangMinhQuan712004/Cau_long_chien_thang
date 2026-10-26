"""Chốt chặn trước khi test xóa sạch DB (``DROP SCHEMA public CASCADE``).

Chỉ cho phép khi DB là DB test (tên kết thúc ``_test``) hoặc đang chạy CI (GitHub Actions đặt
``CI=true``, DB trong container dùng một lần). Luôn từ chối khi ``ENV=production``.
"""

from sqlalchemy.engine import make_url


def reset_refusal(database_url: str, env: str, ci: str | None) -> str | None:
    """Trả lý do từ chối reset DB, hoặc ``None`` nếu được phép."""
    name = make_url(database_url).database or ""
    if env == "production":
        return f"Từ chối reset DB khi ENV=production (DB: {name})."
    if name.endswith("_test") or ci == "true":
        return None
    return f"Từ chối reset DB không phải DB test: {name}"
