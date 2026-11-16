"""Ảnh đại diện hội viên (T-016 AC18–AC19, ADR-009 §5).

Xử lý ảnh nằm ở ``core/images.py`` (dùng chung); ở đây: lưu theo hội viên.
"""

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import images
from app.core.audit import AuditActor, audit, audit_change, audit_detail
from app.core.config import settings
from app.core.images import CONTENT_TYPE, StoredImage
from app.modules.members.models import Customer, CustomerAvatar


def avatar_url(customer_id: int, etag: str | None) -> str | None:
    """Link ảnh hội viên, gồm ``?v={etag}`` để phá cache; chưa có ảnh -> None."""
    if etag is None:
        return None
    return f"{settings.API_PREFIX}/member-area/avatars/{customer_id}?v={etag}"


async def etag_of_customer(session: AsyncSession, customer_id: int) -> str | None:
    """Chỉ đọc etag, không tải bytes của ảnh."""
    return await session.scalar(
        select(CustomerAvatar.etag).where(CustomerAvatar.customer_id == customer_id)
    )


async def save(
    session: AsyncSession, customer: Customer, data: bytes, actor: AuditActor
) -> StoredImage:
    """Ghi đè ảnh (không commit) + nhật ký ``member.avatar_update``."""
    etag = images.etag_of(data)
    await session.execute(
        insert(CustomerAvatar)
        .values(customer_id=customer.id, content_type=CONTENT_TYPE, bytes=data, etag=etag)
        .on_conflict_do_update(
            index_elements=[CustomerAvatar.customer_id],
            set_={"content_type": CONTENT_TYPE, "bytes": data, "etag": etag},
        )
    )
    detail = audit_detail(
        customer.member_code,
        customer.full_name,
        [audit_change("Ảnh đại diện", None, "Ảnh mới")],
    )
    audit(session, actor, "member.avatar_update", "customer", customer.member_code, detail)
    return StoredImage(data, etag, CONTENT_TYPE)


async def remove(session: AsyncSession, customer: Customer, actor: AuditActor) -> bool:
    result = await session.execute(
        delete(CustomerAvatar).where(CustomerAvatar.customer_id == customer.id)
    )
    if not result.rowcount:
        return False
    detail = audit_detail(
        customer.member_code,
        customer.full_name,
        [audit_change("Ảnh đại diện", "Có ảnh", None)],
    )
    audit(session, actor, "member.avatar_delete", "customer", customer.member_code, detail)
    return True


async def load(session: AsyncSession, customer_id: int) -> StoredImage | None:
    row = await session.scalar(
        select(CustomerAvatar).where(CustomerAvatar.customer_id == customer_id)
    )
    return StoredImage(row.bytes, row.etag, row.content_type) if row else None
