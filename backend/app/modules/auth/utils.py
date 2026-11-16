"""Tiện ích auth (port PR #17): chuẩn hóa SĐT, ô đăng nhập, quy tắc mật khẩu, mã + tên NV."""

import re
import secrets
import unicodedata
from typing import Literal

_PHONE_CHARS = re.compile(r"^\+?[\d\s.\-]+$")
_VN_PHONE = re.compile(r"^0\d{9}$")
USERNAME_MAX = 30
# Đuôi ngẫu nhiên của tên đăng nhập NV: chữ thường + số, bỏ ký tự dễ nhầm (0 o 1 l i)
USERNAME_TAIL_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
USERNAME_TAIL_LEN = 4
USERNAME_TAIL_PATTERN = rf"^[{USERNAME_TAIL_ALPHABET}]{{{USERNAME_TAIL_LEN}}}$"
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


def staff_username(full_name: str, tail: str | None = None) -> str:
    """``<cả họ tên liền, không dấu>.<4 ký tự ngẫu nhiên>`` (≤ 30 ký tự, cắt phần họ tên):
    Nguyễn Văn An -> ``nguyenvanan.k7q2``; không có chữ hợp lệ -> ``nv.k7q2``.

    Đuôi ngẫu nhiên thay mã NV tăng dần để khó đoán tên đăng nhập (người dùng chốt 2026-11-05;
    tài khoản cũ giữ nguyên)."""
    tail = tail or "".join(secrets.choice(USERNAME_TAIL_ALPHABET) for _ in range(USERNAME_TAIL_LEN))
    name = "".join(map(_ascii_word, full_name.split())) or "nv"
    return f"{name[: USERNAME_MAX - len(tail) - 1]}.{tail}"


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


DeviceType = Literal["desktop", "mobile", "tablet", "unknown"]

# Thứ tự quan trọng: UA của Edge / Cốc Cốc / Zalo đều chứa "Chrome", Chrome chứa "Safari"
_BROWSERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Zalo", re.compile(r"Zalo", re.I)),
    ("Cốc Cốc", re.compile(r"coc_coc|CocCoc", re.I)),
    ("Edge", re.compile(r"Edg(e|A|iOS)?/")),
    ("Opera", re.compile(r"OPR/|Opera")),
    ("Samsung Internet", re.compile(r"SamsungBrowser/")),
    ("Firefox", re.compile(r"Firefox/|FxiOS/")),
    ("Chrome", re.compile(r"Chrome/|CriOS/")),
    ("Safari", re.compile(r"Version/[\d.]+.*Safari/")),
)
# iOS trước macOS (UA iPad / iPhone có "like Mac OS X"); Android trước Linux
_OSES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Windows", re.compile(r"Windows NT|Windows Phone")),
    ("iOS", re.compile(r"iPhone|iPad|iPod")),
    ("Android", re.compile(r"Android")),
    ("ChromeOS", re.compile(r"CrOS")),
    ("macOS", re.compile(r"Macintosh|Mac OS X")),
    ("Linux", re.compile(r"Linux")),
)


def _first_match(rules: tuple[tuple[str, re.Pattern[str]], ...], ua: str) -> str | None:
    return next((name for name, pattern in rules if pattern.search(ua)), None)


def parse_user_agent(ua: str | None) -> tuple[DeviceType, str | None, str | None]:
    """User agent -> (loại thiết bị, hệ điều hành, trình duyệt); không nhận ra -> unknown / None.

    Chỉ để hiện "Nơi bạn đăng nhập" (gần đúng), không dùng cho kiểm tra bảo mật.
    """
    if not ua:
        return "unknown", None, None
    os_name = _first_match(_OSES, ua)
    browser = _first_match(_BROWSERS, ua)
    if re.search(r"iPad|Tablet", ua) or (os_name == "Android" and "Mobile" not in ua):
        device: DeviceType = "tablet"
    elif re.search(r"Mobi|iPhone|iPod", ua):
        device = "mobile"
    elif os_name in {"Windows", "macOS", "Linux", "ChromeOS"}:
        device = "desktop"
    else:
        device = "unknown"
    return device, os_name, browser
