"""Ảnh đại diện hội viên (T-016 AC18–AC19, ADR-009 §5).

Không bao giờ lưu nguyên tệp người dùng gửi: kiểm magic bytes, giải mã bằng Pillow (đúng định dạng
khai), chặn ảnh > 40 MP (bom ảnh), xoay theo EXIF, cắt vuông theo khung người dùng chọn, thu về
≤ 512 px rồi **mã hóa lại** WebP không metadata. Tệp đa định dạng / SVG / HTML đổi đuôi bị loại.
"""

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit, audit_change, audit_detail
from app.core.config import settings
from app.core.errors import AppError
from app.modules.members.models import Customer, CustomerAvatar

MAX_PIXELS = 40_000_000
OUT_SIZE = 512
CONTENT_TYPE = "image/webp"
# Pillow tự chặn ảnh quá lớn ngay lúc mở (cảnh báo > MAX, lỗi > 2×MAX); ta kiểm chặt hơn ở dưới
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


@dataclass(frozen=True)
class Crop:
    x: int
    y: int
    size: int


@dataclass(frozen=True)
class StoredAvatar:
    data: bytes
    etag: str
    content_type: str


def invalid(message: str = "Ảnh phải là JPG, PNG hoặc WebP, tối đa 5 MB.") -> AppError:
    return AppError("E-HV-13", message, 422)


def sniff(data: bytes) -> str | None:
    """Định dạng theo magic bytes (không tin đuôi tệp / Content-Type)."""
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def process(data: bytes, crop: Crop) -> bytes:
    """Tệp gốc -> WebP vuông ≤ 512 px (lỗi -> 422 ``E-HV-13``).

    ``crop`` tính theo pixel của ảnh **sau khi xoay theo EXIF** (đúng như trình duyệt hiển thị).
    """
    if not data or len(data) > settings.AVATAR_MAX_BYTES:
        raise invalid()
    fmt = sniff(data)
    if fmt is None:
        raise invalid()
    try:
        with Image.open(io.BytesIO(data), formats=[fmt]) as img:
            width, height = img.size
            if width * height > MAX_PIXELS:
                raise invalid("Ảnh quá lớn (tối đa 40 megapixel).")
            img.load()
            oriented = ImageOps.exif_transpose(img)
            width, height = oriented.size
            if (
                crop.size < 1
                or crop.x < 0
                or crop.y < 0
                or crop.x + crop.size > width
                or crop.y + crop.size > height
            ):
                raise invalid("Vùng cắt ảnh không hợp lệ.")
            square = oriented.crop((crop.x, crop.y, crop.x + crop.size, crop.y + crop.size))
            if crop.size > OUT_SIZE:
                square = square.resize((OUT_SIZE, OUT_SIZE), Image.Resampling.LANCZOS)
            has_alpha = square.mode in ("RGBA", "LA", "PA") or "transparency" in square.info
            square = square.convert("RGBA" if has_alpha else "RGB")
            out = io.BytesIO()
            # Không truyền exif / icc -> ảnh ra không mang metadata
            square.save(out, "WEBP", quality=85, method=4)
            return out.getvalue()
    except AppError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        raise invalid() from None


def etag_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


async def save(
    session: AsyncSession, customer: Customer, data: bytes, actor: AuditActor
) -> StoredAvatar:
    """Ghi đè ảnh (không commit) + nhật ký ``member.avatar_update``."""
    etag = etag_of(data)
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
    return StoredAvatar(data, etag, CONTENT_TYPE)


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


async def load(session: AsyncSession, customer_id: int) -> StoredAvatar | None:
    row = await session.scalar(
        select(CustomerAvatar).where(CustomerAvatar.customer_id == customer_id)
    )
    return StoredAvatar(row.bytes, row.etag, row.content_type) if row else None
