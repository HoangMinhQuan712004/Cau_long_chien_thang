"""Đọc "Link Google Maps" Admin dán -> link + tọa độ. Không nhận mã nhúng (người dùng chốt).

Chỉ giữ link đã qua allowlist (trang khách đưa thẳng vào ``<a href>``). Không chạm DB.
"""

import asyncio
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import httpx

from app.core.errors import AppError

MAX_INPUT = 4000
MAX_URL = 2048
MAX_REDIRECTS = 3
TIMEOUT_S = 5
COORD_DIGITS = 7  # ~1 cm, dư cho bản đồ
SHORT_HOST = "maps.app.goo.gl"
ALLOWED_HOSTS = {SHORT_HOST, "www.google.com", "maps.google.com"}
URL_CHARS_RE = re.compile(r"""^[^\s\\<>"'\x00-\x1f]+$""")
_NUM = r"(-?\d{1,3}(?:\.\d+)?)"
PLACE_RE = re.compile(rf"!3d{_NUM}!4d{_NUM}")  # tọa độ đúng của địa điểm
SEARCH_RE = re.compile(rf"/maps/search/{_NUM},[\s+]*{_NUM}")
PAIR_RE = re.compile(rf"^\s*{_NUM}\s*,\s*{_NUM}\s*$")
AT_RE = re.compile(rf"@{_NUM},{_NUM}")  # chỉ là tâm khung nhìn -> xét sau cùng


@dataclass(frozen=True)
class MapInfo:
    map_url: str | None = None
    lat: float | None = None
    lng: float | None = None


def _invalid() -> AppError:
    return AppError("E-001", "Link Google Maps không hợp lệ.", 422)


def _unreachable() -> AppError:
    return AppError("E-001", "Chưa đọc được link, hãy thử lại.", 422)


def is_allowed_link(url: str) -> bool:
    """Chống SSRF: chỉ https, đúng host (không userinfo / cổng), www.google.com chỉ ``/maps``;
    link nhúng ``/maps/embed`` không nhận."""
    if len(url) > MAX_URL or not URL_CHARS_RE.match(url):
        return False
    try:
        parts = urlsplit(url)
        if parts.port is not None:
            return False
    except ValueError:
        return False
    host = parts.hostname
    if parts.scheme != "https" or host not in ALLOWED_HOSTS or parts.netloc != host:
        return False
    if ".." in parts.path or parts.path.startswith("/maps/embed"):
        return False
    return host != "www.google.com" or parts.path == "/maps" or parts.path.startswith("/maps/")


def _valid(lat: float, lng: float) -> tuple[float, float] | None:
    if -90 <= lat <= 90 and -180 <= lng <= 180:
        return round(lat, COORD_DIGITS), round(lng, COORD_DIGITS)
    return None


def coords_in_link(url: str) -> tuple[float, float] | None:
    """Ưu tiên ``!3d!4d``, rồi ``/maps/search/lat,lng``, ``q=``, cuối cùng ``@``."""
    plain = unquote(url)
    query = parse_qs(urlsplit(url).query)
    q = PAIR_RE.match((query.get("q") or query.get("query") or [""])[0])
    for found in (PLACE_RE.search(plain), SEARCH_RE.search(plain), q, AT_RE.search(plain)):
        if found and (coords := _valid(float(found[1]), float(found[2]))):
            return coords
    return None


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(follow_redirects=False, timeout=TIMEOUT_S)


async def _follow_short_link(url: str) -> str:
    """Theo chuyển hướng bằng tay để kiểm allowlist TỪNG lần; không đọc body, client mới mỗi lần
    (không mang cookie). Hết giờ / lỗi mạng -> báo thử lại; host lạ -> link không hợp lệ."""
    try:
        async with asyncio.timeout(TIMEOUT_S):
            for _ in range(MAX_REDIRECTS + 1):
                async with _client() as client, client.stream("GET", url) as response:
                    if not response.has_redirect_location:
                        if response.status_code >= 400:
                            raise _unreachable()
                        return url
                    target = urljoin(url, response.headers["location"])
                if not is_allowed_link(target):
                    raise _invalid()
                url = target
    except (httpx.HTTPError, TimeoutError):
        raise _unreachable() from None
    raise _unreachable()  # quá số lần chuyển hướng


async def resolve(raw: str) -> MapInfo:
    """Link -> ``map_url`` (giữ link Admin dán) + tọa độ nếu có; iframe / thứ khác -> 422."""
    text = raw.strip()
    if not is_allowed_link(text):
        raise _invalid()
    final = await _follow_short_link(text) if urlsplit(text).hostname == SHORT_HOST else text
    lat, lng = coords_in_link(final) or (None, None)
    return MapInfo(map_url=text, lat=lat, lng=lng)


def check_saved(map_url: str | None, lat: float | None, lng: float | None) -> MapInfo:
    """Kiểm lại lúc lưu, cùng luật (không tin FE, không gọi mạng). Mọi trường null = bỏ bản đồ."""
    map_url = map_url or None
    if map_url is not None and not is_allowed_link(map_url):
        raise _invalid()
    if lat is None and lng is None:
        return MapInfo(map_url)
    # Tọa độ phải đi kèm link: không có ô nhập tọa độ riêng
    if lat is None or lng is None or map_url is None:
        raise _invalid()
    coords = _valid(lat, lng)
    if coords is None:
        raise _invalid()
    return MapInfo(map_url, *coords)
