"""Hàm dùng chung của auth: chuẩn hóa SĐT/tên đăng nhập, luật mật khẩu, kiểm ID token Google."""

import asyncio
import re
import unicodedata
from functools import cache
from typing import Literal, NamedTuple

import jwt

from app.core.config import settings

_PHONE_CHARS = re.compile(r"^\+?[\d\s.\-]+$")
_VN_PHONE = re.compile(r"^0\d{9}$")
_USERNAME_MAX = 30
PASSWORD_MIN = 8
GOOGLE_JWKS_URL = "https://www.googleapis.com/oauth2/v3/certs"
GOOGLE_ISSUERS = ["accounts.google.com", "https://accounts.google.com"]


# --- SĐT / tên đăng nhập ---
def normalize_phone(raw: str) -> str | None:
    """Chuẩn hóa SĐT về `0xxxxxxxxx` (`+84…`, có dấu cách); không phải SĐT ⇒ None."""
    if not _PHONE_CHARS.match(raw.strip()):
        return None
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("84") and len(digits) == 11:
        digits = "0" + digits[2:]
    return digits if _VN_PHONE.match(digits) else None


def parse_login(raw: str) -> tuple[Literal["phone", "username"], str]:
    """Ô đăng nhập: SĐT nếu chuẩn hóa được, ngược lại là tên đăng nhập chữ thường."""
    phone = normalize_phone(raw)
    if phone is not None:
        return "phone", phone
    return "username", raw.strip().lower()


def staff_code(number: int) -> str:
    """Mã nhân viên từ sequence: 7 ⇒ `NV007`."""
    return f"NV{number:03d}"


def _ascii_word(word: str) -> str:
    """Bỏ dấu, chữ thường, chỉ giữ a-z 0-9 (`Đạt` ⇒ `dat`)."""
    word = word.replace("đ", "d").replace("Đ", "D")
    plain = unicodedata.normalize("NFD", word).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", plain.lower())


def staff_username(full_name: str, code: str) -> str:
    """Tên đăng nhập nhân viên `<tên gọi>.<mã>` (≤ 30 ký tự): Nguyễn Văn An, NV007 ⇒ `an.nv007`."""
    suffix = code.lower()
    words = [w for w in map(_ascii_word, full_name.split()) if w]
    if not words:
        return suffix
    return f"{words[-1][: _USERNAME_MAX - len(suffix) - 1]}.{suffix}"


# --- Mật khẩu mới ---
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
    """Câu báo lỗi từ `password_problems`."""
    head = ", ".join(problems[:-1])
    return f"Mật khẩu cần {head + ' và ' if head else ''}{problems[-1]}."


# --- Google ID token (OIDC) ---
class GoogleTokenError(Exception):
    """ID token sai (chữ ký, aud, iss, hạn, sub)."""


class GoogleUnavailable(Exception):
    """Không tải được khóa công khai của Google."""


class GoogleIdentity(NamedTuple):
    sub: str
    name: str | None
    email: str | None  # chỉ khi `email_verified`


@cache
def _jwks_client() -> jwt.PyJWKClient:
    """Bộ khóa Google, cache 1 giờ, `kid` lạ thì tải lại."""
    return jwt.PyJWKClient(GOOGLE_JWKS_URL, cache_jwk_set=True, lifespan=3600, timeout=5)


async def verify_google_id_token(credential: str) -> GoogleIdentity:
    """Kiểm ID token Google (RS256, aud = GOOGLE_CLIENT_ID, iss, exp) ⇒ danh tính."""
    try:
        # urllib chặn ⇒ chạy ở thread
        key = await asyncio.to_thread(_jwks_client().get_signing_key_from_jwt, credential)
    except jwt.PyJWKClientConnectionError as e:
        raise GoogleUnavailable from e
    except jwt.PyJWTError as e:
        raise GoogleTokenError from e
    try:
        payload = jwt.decode(
            credential,
            key.key,
            algorithms=["RS256"],
            audience=settings.GOOGLE_CLIENT_ID,
            issuer=GOOGLE_ISSUERS,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as e:
        raise GoogleTokenError from e
    sub = payload["sub"]
    if not isinstance(sub, str) or not sub or len(sub) > 255:
        raise GoogleTokenError
    name = payload.get("name")
    email = payload.get("email") if payload.get("email_verified") is True else None
    return GoogleIdentity(
        sub=sub,
        name=name[:255] if isinstance(name, str) and name.strip() else None,
        email=email[:255] if isinstance(email, str) else None,
    )
