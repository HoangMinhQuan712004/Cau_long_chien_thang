from datetime import UTC, datetime, timedelta
from typing import Literal

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


def create_token(subject: str, token_type: TokenType) -> str:
    if token_type == "access":
        expires = timedelta(minutes=settings.ACCESS_TOKEN_MINUTES)
    else:
        expires = timedelta(days=settings.REFRESH_TOKEN_DAYS)
    now = datetime.now(UTC)
    payload = {"sub": subject, "type": token_type, "iat": now, "exp": now + expires}
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str, token_type: TokenType) -> str | None:
    """Trả về subject (user id) nếu token hợp lệ và đúng loại, ngược lại None."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != token_type:
        return None
    return payload.get("sub")
