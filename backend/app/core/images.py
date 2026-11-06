"""Xử lý ảnh người dùng tải lên – dùng chung cho ảnh đại diện hội viên / quản trị (ADR-009 §5).

Không bao giờ lưu nguyên tệp người dùng gửi: kiểm magic bytes, giải mã bằng Pillow (đúng định dạng
khai), chặn ảnh > 40 MP (bom ảnh), xoay theo EXIF, cắt vuông theo khung người dùng chọn, thu về
≤ 512 px rồi **mã hóa lại** WebP không metadata. Tệp đa định dạng / SVG / HTML đổi đuôi bị loại.
"""

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError
from starlette.responses import Response

from app.core.config import settings
from app.core.errors import AppError

MAX_PIXELS = 40_000_000
OUT_SIZE = 512
# Link ảnh có ``?v={etag}``: nội dung không đổi
CACHE_IMMUTABLE = "public, max-age=31536000, immutable"
CONTENT_TYPE = "image/webp"
_BAD_IMAGE = (
    UnidentifiedImageError,
    Image.DecompressionBombError,
    OSError,
    ValueError,
    SyntaxError,
)
# Pillow tự chặn ảnh quá lớn ngay lúc mở (cảnh báo > MAX, lỗi > 2×MAX); ta kiểm chặt hơn ở dưới
Image.MAX_IMAGE_PIXELS = MAX_PIXELS


def _rejected(message: str = "Ảnh phải là JPG, PNG hoặc WebP, tối đa 5 MB.") -> AppError:
    """Mọi màn tải ảnh dùng chung mã + câu: FE dùng chung hộp cắt ảnh."""
    return AppError("E-HV-13", message, 422)


@dataclass(frozen=True)
class Crop:
    x: int
    y: int
    size: int


@dataclass(frozen=True)
class StoredImage:
    data: bytes
    etag: str
    content_type: str


def sniff(data: bytes) -> str | None:
    """Định dạng theo magic bytes (không tin đuôi tệp / Content-Type)."""
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def _decode_square(data: bytes, crop: Crop) -> Image.Image:
    """Kiểm tệp, giải mã, xoay theo EXIF, cắt vuông (chưa đổi cỡ, chưa đổi mode).

    ``crop`` tính theo pixel của ảnh **sau khi xoay theo EXIF** (đúng như trình duyệt hiển thị).
    """
    if not data or len(data) > settings.AVATAR_MAX_BYTES:
        raise _rejected()
    fmt = sniff(data)
    if fmt is None:
        raise _rejected()
    try:
        with Image.open(io.BytesIO(data), formats=[fmt]) as img:
            width, height = img.size
            if width * height > MAX_PIXELS:
                raise _rejected("Ảnh quá lớn (tối đa 40 megapixel).")
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
                raise _rejected("Vùng cắt ảnh không hợp lệ.")
            return oriented.crop((crop.x, crop.y, crop.x + crop.size, crop.y + crop.size))
    except _BAD_IMAGE:
        raise _rejected() from None


def process_square(data: bytes, crop: Crop) -> bytes:
    """Tệp gốc -> WebP vuông ≤ 512 px (lỗi -> 422 ``E-HV-13``)."""
    square = _decode_square(data, crop)
    try:
        if crop.size > OUT_SIZE:
            square = square.resize((OUT_SIZE, OUT_SIZE), Image.Resampling.LANCZOS)
        has_alpha = square.mode in ("RGBA", "LA", "PA") or "transparency" in square.info
        square = square.convert("RGBA" if has_alpha else "RGB")
        out = io.BytesIO()
        # Không truyền exif / icc -> ảnh ra không mang metadata
        square.save(out, "WEBP", quality=85, method=4)
        return out.getvalue()
    except _BAD_IMAGE:
        raise _rejected() from None


def etag_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:16]


def image_response(
    stored: StoredImage | None, if_none_match: str | None, cache_control: str
) -> Response:
    """Trả ảnh đã lưu: 404 nếu chưa có, 304 nếu trình duyệt đã có đúng etag."""
    if stored is None:
        return Response(status_code=404, headers={"Cache-Control": "no-store"})
    etag = f'"{stored.etag}"'
    headers = {
        "ETag": etag,
        "Cache-Control": cache_control,
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; sandbox",
        "Content-Disposition": "inline",
    }
    if if_none_match and etag in [t.strip() for t in if_none_match.split(",")]:
        return Response(status_code=304, headers=headers)
    return Response(content=stored.data, media_type=stored.content_type, headers=headers)
