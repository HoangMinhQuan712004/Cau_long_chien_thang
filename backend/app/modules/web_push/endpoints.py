"""Chống SSRF (T-076 Q7): chỉ nhận / gửi tới endpoint của dịch vụ push đã biết.

- ``https`` · cổng 443 hoặc không ghi cổng · không userinfo · host là tên miền (không IP).
- ``fcm.googleapis.com``, ``updates.push.services.mozilla.com``: khớp chính xác.
- ``*.push.apple.com``, ``*.notify.windows.com``: chỉ tên miền con (không khớp tên miền gốc).
"""

import ipaddress
from urllib.parse import urlsplit

from app.core.errors import AppError

EXACT_HOSTS = frozenset({"fcm.googleapis.com", "updates.push.services.mozilla.com"})
SUFFIX_HOSTS = (".push.apple.com", ".notify.windows.com")
ENDPOINT_MAX = 1000


def unsupported() -> AppError:
    return AppError("E-PUSH-1", "Thiết bị này không hỗ trợ nhận thông báo.", 422)


def _allowed_host(host: str) -> bool:
    if host in EXACT_HOSTS:
        return True
    return any(host.endswith(s) and len(host) > len(s) for s in SUFFIX_HOSTS)


def host_of(endpoint: str) -> str | None:
    """Host đã chuẩn hóa nếu endpoint hợp lệ, ngược lại None. Dùng cả khi nhận và trước khi gửi."""
    if not endpoint or len(endpoint) > ENDPOINT_MAX or any(c.isspace() for c in endpoint):
        return None
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        return None
    if parts.scheme != "https" or parts.username is not None or parts.password is not None:
        return None
    if "@" in parts.netloc or port not in (None, 443):
        return None
    host = (parts.hostname or "").lower()
    # Nhãn rỗng (``..push.apple.com``, ``.fcm…``, dấu chấm cuối) -> không phải tên miền hợp lệ
    if not host or any(label == "" for label in host.split(".")):
        return None
    try:
        ipaddress.ip_address(host)
        return None  # IP (kể cả IP nội bộ) không bao giờ là dịch vụ push
    except ValueError:
        pass
    return host if _allowed_host(host) else None


def raw_host(endpoint: str) -> str:
    """Host để ghi log (không bao giờ ghi cả URL); không đọc được -> ``?``."""
    try:
        return (urlsplit(endpoint).hostname or "?")[:100]
    except ValueError:
        return "?"


def check(endpoint: str) -> str:
    """Host của endpoint hợp lệ; sai -> 422 E-PUSH-1."""
    host = host_of(endpoint)
    if host is None:
        raise unsupported()
    return host
