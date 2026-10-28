"""Tiện ích auth (port PR #17): chuẩn hóa SĐT, ô đăng nhập, quy tắc mật khẩu, mã + tên NV."""

import re
import unicodedata
from typing import Literal

_PHONE_CHARS = re.compile(r"^\+?[\d\s.\-]+$")
_VN_PHONE = re.compile(r"^0\d{9}$")
USERNAME_MAX = 30
PASSWORD_MIN = 8


def normalize_phone(raw: str) -> str | None:
    """``+84 912.345-678`` -> ``0912345678``; không phải SĐT di động VN 10 số -> None."""
    if not raw or not _PHONE_CHARS.match(raw.strip()):
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits if _VN_PHONE.match(digits) else None


def parse_login(raw: str) -> tuple[Literal["phone", "username"], str]:
    """Ô "Số điện thoại hoặc tên đăng nhập": SĐT nếu chuẩn hóa được, còn lại tên chữ thường."""
    phone = normalize_phone(raw)
    if phone is not None:
        return "phone", phone
    return "username", raw.strip().lower()


def staff_code(number: int) -> str:
    """Số từ sequence -> ``NV007``."""
    return f"NV{number:03d}"


def _ascii_word(word: str) -> str:
    word = word.replace("đ", "d").replace("Đ", "D")
    plain = unicodedata.normalize("NFD", word).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", plain.lower())


def staff_username(full_name: str, code: str) -> str:
    """``<tên gọi>.<mã>`` (≤ 30 ký tự): Nguyễn Văn An, NV007 -> ``an.nv007``."""
    suffix = code.lower()
    words = [w for w in map(_ascii_word, full_name.split()) if w]
    if not words:
        return suffix
    return f"{words[-1][: USERNAME_MAX - len(suffix) - 1]}.{suffix}"


def password_problems(password: str) -> list[str]:
    """Phần còn thiếu: ≥ 8 ký tự, 1 chữ in hoa, 1 chữ số hoặc ký tự đặc biệt; rỗng = đạt."""
    problems = []
    if len(password) < PASSWORD_MIN:
        problems.append(f"ít nhất {PASSWORD_MIN} ký tự")
    if not any(c.isupper() for c in password):
        problems.append("1 chữ in hoa")
    if not any(c.isdigit() or (not c.isalnum() and not c.isspace()) for c in password):
        problems.append("1 chữ số hoặc ký tự đặc biệt")
    return problems


def password_rule_message(problems: list[str]) -> str:
    head = ", ".join(problems[:-1])
    return f"Mật khẩu cần {head + ' và ' if head else ''}{problems[-1]}."
