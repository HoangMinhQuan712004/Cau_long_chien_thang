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
