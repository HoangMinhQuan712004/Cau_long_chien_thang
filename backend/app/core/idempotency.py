"""Chống bấm 2 lần / gửi lại (ADR-004 S10, SRS NFR-004).

Route ghi khai báo ``idem: IdempotencyDep`` và chạy nghiệp vụ qua ``idem.run(...)``:

- Header ``Idempotency-Key`` (UUID v4) bắt buộc -> thiếu / sai dạng: 400 ``E-SEC-2``.
- Cùng (người thao tác, key) đang được xử lý ở request khác -> 409 ``E-SEC-3``
  (khóa ``pg_try_advisory_xact_lock`` – không chờ).
- Đã xử lý xong + cùng nội dung -> trả lại **đúng response cũ**
  (header ``Idempotent-Replayed: true``).
- Đã dùng key với nội dung khác -> 422 ``E-SEC-4``.

Kết quả được ghi vào ``idempotency_keys`` **trong cùng transaction** với nghiệp vụ rồi commit
một lần: nghiệp vụ lỗi -> rollback cả hai, gửi lại sẽ chạy lại; không có dòng "đang xử lý"
bị treo khi tiến trình chết.
Hàm nghiệp vụ truyền vào ``run`` **không được commit**. Key giữ 24 giờ (job ``purge_expired``).
"""

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, Header, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import DateTime, SmallInteger, String, Uuid, func, select, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base
from app.core.errors import AppError

HEADER = "Idempotency-Key"
RETENTION = "24 hours"


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    actor_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    key: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    method_path: Mapped[str] = mapped_column(String(300))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int] = mapped_column(SmallInteger)
    response: Mapped[Any] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


def _response(status_code: int, payload: Any, replayed: bool) -> Response:
    headers = {"Idempotent-Replayed": "true"} if replayed else None
    if status_code == 204 or payload is None:
        return Response(status_code=status_code, headers=headers)
    return JSONResponse(payload, status_code=status_code, headers=headers)


class Idempotency:
    def __init__(self, key: uuid.UUID, method_path: str, request_hash: str):
        self.key = key
        self.method_path = method_path
        self.request_hash = request_hash

    def _lock_id(self, actor_key: str) -> int:
        digest = hashlib.sha256(f"{actor_key}|{self.key}".encode()).digest()
        return int.from_bytes(digest[:8], "big", signed=True)

    async def run(
        self,
        session: AsyncSession,
        actor_key: str,
        fn: Callable[[], Awaitable[Any]],
        status_code: int = 200,
    ) -> Response:
        """Chạy ``fn`` đúng một lần cho (actor_key, key); commit nghiệp vụ + kết quả cùng lúc."""
        locked = await session.scalar(
            select(func.pg_try_advisory_xact_lock(self._lock_id(actor_key)))
        )
        if not locked:
            await session.rollback()
            raise AppError("E-SEC-3", "Thao tác đang được xử lý. Vui lòng chờ trong giây lát.", 409)
        existing = await session.get(IdempotencyKey, (actor_key, self.key))
        if existing is not None:
            # Đọc trước khi rollback (rollback làm hết hạn thuộc tính ORM)
            same = existing.request_hash == self.request_hash
            stored_status, stored = existing.status_code, existing.response
            await session.rollback()
            if not same:
                raise AppError("E-SEC-4", "Mã thao tác đã được dùng cho một yêu cầu khác.", 422)
            return _response(stored_status, stored, replayed=True)

        try:
            result = await fn()
        except BaseException:
            await session.rollback()
            raise
        payload = jsonable_encoder(result) if result is not None else None
        session.add(
            IdempotencyKey(
                actor_key=actor_key,
                key=self.key,
                method_path=self.method_path,
                request_hash=self.request_hash,
                status_code=status_code,
                response=payload,
            )
        )
        await session.commit()
        return _response(status_code, payload, replayed=False)


def _canonical_body(raw: bytes) -> bytes:
    if not raw:
        return b""
    try:
        return json.dumps(json.loads(raw), sort_keys=True, separators=(",", ":")).encode()
    except ValueError:
        return raw


async def idempotency(
    request: Request,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias=HEADER,
            description="UUID v4 sinh khi người dùng bấm nút; giữ nguyên khi tự thử lại.",
        ),
    ] = None,
) -> Idempotency:
    try:
        key = uuid.UUID(idempotency_key or "")
    except ValueError:
        key = None
    if key is None or key.version != 4:
        raise AppError("E-SEC-2", "Thiếu hoặc sai mã thao tác (Idempotency-Key).", 400)
    method_path = f"{request.method} {request.url.path}"
    digest = hashlib.sha256(method_path.encode() + b"\n" + _canonical_body(await request.body()))
    return Idempotency(key, method_path, digest.hexdigest())


IdempotencyDep = Annotated[Idempotency, Depends(idempotency)]


async def purge_expired(session: AsyncSession) -> int:
    result = await session.execute(
        text(f"DELETE FROM idempotency_keys WHERE created_at < now() - interval '{RETENTION}'")
    )
    await session.commit()
    return result.rowcount or 0
