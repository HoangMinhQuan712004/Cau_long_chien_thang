from datetime import UTC, datetime, timedelta
from typing import Literal, NamedTuple

import jwt
from pwdlib import PasswordHash

from app.core.config import settings

ALGORITHM = "HS256"
TokenType = Literal["access", "refresh"]

password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    return password_hash.verify(password, hashed)


def create_token(subject: str, token_type: TokenType, version: int) -> str:
    """`version` = `User.token_version` lúc cấp (claim `ver`)."""
    if token_type == "access":
        expires = timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)
    else:
        expires = timedelta(days=settings.REFRESH_TOKEN_DAYS)
    now = datetime.now(UTC)
    payload = {
        "sub": subject,
        "type": token_type,
        "ver": version,
        "iat": now,
        "exp": now + expires,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


class TokenClaims(NamedTuple):
    subject: str
    version: int


def decode_token(token: str, token_type: TokenType) -> TokenClaims | None:
    """Giải mã JWT khách đúng loại ⇒ (user id, ver; thiếu ver = 0), sai ⇒ None."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    subject, version = payload.get("sub"), payload.get("ver", 0)
    # sub phải là id số
    if (
        payload.get("type") != token_type
        or not isinstance(subject, str)
        or not subject.isdecimal()
        or type(version) is not int
    ):
        return None
    return TokenClaims(subject, version)
