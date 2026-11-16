"""Link video kỷ lục (T-046): Admin dán link, hệ thống không lưu file.

Chỉ nhận ``https://``:
- YouTube (``youtube.com/watch?v=…``, ``youtu.be/…``, ``youtube.com/shorts/…``) -> FE nhúng
  ``youtube-nocookie.com/embed/{id}``, ảnh xem trước ``i.ytimg.com`` (chưa nạp script khi chưa bấm);
- file video trực tiếp đuôi ``.mp4`` / ``.webm`` -> FE phát bằng ``<video>``.
"""

import re
from urllib.parse import parse_qs, urlsplit

from app.core.errors import AppError
from app.modules.records.schemas import VideoOut

MAX_LEN = 500
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com"}
YOUTU_BE = {"youtu.be", "www.youtu.be"}
YOUTUBE_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
FILE_SUFFIXES = (".mp4", ".webm")


def bad_link() -> AppError:
    return AppError("E-REC-1", "Chỉ nhận link YouTube hoặc file .mp4 / .webm (https).", 422)


def _youtube_id(host: str, path: str, query: str) -> str | None:
    if host in YOUTU_BE:
        vid = path.strip("/").split("/")[0]
    elif host in YOUTUBE_HOSTS and path == "/watch":
        vid = (parse_qs(query).get("v") or [""])[0]
    elif host in YOUTUBE_HOSTS and path.startswith("/shorts/"):
        vid = path.removeprefix("/shorts/").split("/")[0]
    else:
        return None
    return vid if YOUTUBE_ID.match(vid) else None


def parse(url: str | None) -> VideoOut | None:
    """Link đã lưu -> ``VideoOut``; link rỗng / không hợp lệ (dữ liệu cũ) -> None."""
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme != "https" or not parts.hostname:
        return None
    host = parts.hostname.lower()
    vid = _youtube_id(host, parts.path, parts.query)
    if vid is not None:
        return VideoOut(
            kind="youtube",
            url=url,
            embed_url=f"https://www.youtube-nocookie.com/embed/{vid}",
            thumbnail_url=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg",
        )
    if host in YOUTUBE_HOSTS or host in YOUTU_BE:
        return None  # link YouTube nhưng không có id video hợp lệ
    if parts.path.lower().endswith(FILE_SUFFIXES):
        return VideoOut(kind="file", url=url, embed_url=None, thumbnail_url=None)
    return None


def clean(raw: str) -> str:
    """Link Admin dán -> link lưu (cắt khoảng trắng); không hợp lệ -> 422 E-REC-1."""
    url = (raw or "").strip()
    if not url or len(url) > MAX_LEN or any(c.isspace() for c in url) or parse(url) is None:
        raise bad_link()
    return url
