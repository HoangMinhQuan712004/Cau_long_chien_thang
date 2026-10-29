"""Che dữ liệu cá nhân trong response (SRS BR-021, ADR-004 S12)."""


def mask_phone(phone: str | None) -> str | None:
    """``0987654321`` -> ``0987 xxx 321``. Số quá ngắn chỉ giữ 2 chữ số cuối."""
    if not phone:
        return phone
    digits = "".join(ch for ch in phone if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]} xxx {digits[-3:]}"
    if len(digits) >= 3:
        return f"xxx {digits[-2:]}"
    return "xxx"


def mask_ip(ip: str | None) -> str | None:
    """IPv4 ``203.0.113.25`` -> ``203.0.113.xxx``; IPv6 giữ 3 nhóm đầu (``2001:db8:1::xxx``)."""
    if not ip:
        return ip
    if "." in ip and ":" not in ip:
        parts = ip.split(".")
        return ".".join(parts[:3] + ["xxx"]) if len(parts) == 4 else "xxx"
    groups = [g for g in ip.split(":") if g]
    return ":".join(groups[:3]) + "::xxx" if groups else "xxx"
