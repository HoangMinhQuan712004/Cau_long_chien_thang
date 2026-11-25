"""Phát video kỷ lục máy đo cắt ra qua chính domain của web (``GET /api/v1/clips/{bucket}/{key}``).

MinIO của máy đo chỉ có http; trang https không phát được video http (mixed content). Route này
chuyển tiếp (stream, có Range để tua) file từ ``CLIPS_ORIGIN`` – chỉ bucket ``CLIPS_BUCKET``, chỉ
đọc, không cần đăng nhập (link nằm trong số đo đã duyệt, như link YouTube Admin dán). Tắt (404)
khi ``CLIPS_ORIGIN`` trống.
"""

import logging
import re

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask

from app.core.config import settings
from app.core.errors import AppError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/clips", tags=["records"])

KEY = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_./-]{0,400}\.(mp4|webm)$")
PASSED = (
    "content-type",
    "content-length",
    "content-range",
    "accept-ranges",
    "etag",
    "last-modified",
)
TIMEOUT = httpx.Timeout(10.0, read=30.0)


def _missing() -> AppError:
    return AppError("E-REC-9", "Không tìm thấy video.", 404)


def _upstream(bucket: str, key: str) -> str:
    if not settings.CLIPS_ORIGIN or bucket != settings.CLIPS_BUCKET:
        raise _missing()
    if not KEY.match(key) or ".." in key or "//" in key:
        raise _missing()
    return f"{settings.CLIPS_ORIGIN.rstrip('/')}/{bucket}/{key}"


@router.api_route("/{bucket}/{key:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def clip(bucket: str, key: str, request: Request) -> Response:
    url = _upstream(bucket, key)
    headers = {"Accept-Encoding": "identity"}  # byte nguyên văn: Content-Length / Range khớp
    if rng := request.headers.get("range"):
        headers["Range"] = rng[:100]
    client = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)
    try:
        upstream = await client.send(
            client.build_request(request.method, url, headers=headers), stream=True
        )
    except httpx.HTTPError as exc:
        await client.aclose()
        logger.warning("Clips: upstream unreachable (%s)", type(exc).__name__)
        raise AppError("E-REC-10", "Chưa phát được video, thử lại sau.", 502) from None
    if upstream.status_code not in (200, 206):
        status = upstream.status_code
        await upstream.aclose()
        await client.aclose()
        if status == 416:
            return Response(status_code=416)
        raise _missing()
    out = {k: v for k, v in upstream.headers.items() if k.lower() in PASSED}
    out["Cache-Control"] = "public, max-age=86400"

    async def close() -> None:
        await upstream.aclose()
        await client.aclose()

    if request.method == "HEAD":
        await close()
        return Response(status_code=upstream.status_code, headers=out)
    return StreamingResponse(
        upstream.aiter_bytes(),
        status_code=upstream.status_code,
        headers=out,
        background=BackgroundTask(close),
    )
