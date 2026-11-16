"""Danh sách ngân hàng nhận tiền (mã VietQR) – cố định trong code (T-012 AC2).

``code``: mã VietQR lưu trong cài đặt; ``short_name``: tên dùng cho tham số ``bank`` của
``qr.sepay.vn``; ``name``: tên đầy đủ hiển thị.
"""

from pydantic import BaseModel


class Bank(BaseModel):
    code: str
    short_name: str
    name: str


BANKS: list[Bank] = [
    Bank(code=c, short_name=s, name=n)
    for c, s, n in (
        ("VCB", "Vietcombank", "Ngân hàng TMCP Ngoại Thương Việt Nam"),
        ("BIDV", "BIDV", "Ngân hàng TMCP Đầu tư và Phát triển Việt Nam"),
        ("ICB", "VietinBank", "Ngân hàng TMCP Công thương Việt Nam"),
        ("VBA", "Agribank", "Ngân hàng Nông nghiệp và Phát triển Nông thôn Việt Nam"),
        ("MB", "MBBank", "Ngân hàng TMCP Quân đội"),
        ("TCB", "Techcombank", "Ngân hàng TMCP Kỹ thương Việt Nam"),
        ("ACB", "ACB", "Ngân hàng TMCP Á Châu"),
        ("VPB", "VPBank", "Ngân hàng TMCP Việt Nam Thịnh Vượng"),
        ("TPB", "TPBank", "Ngân hàng TMCP Tiên Phong"),
        ("STB", "Sacombank", "Ngân hàng TMCP Sài Gòn Thương Tín"),
        ("HDB", "HDBank", "Ngân hàng TMCP Phát triển Thành phố Hồ Chí Minh"),
        ("VIB", "VIB", "Ngân hàng TMCP Quốc tế Việt Nam"),
        ("SHB", "SHB", "Ngân hàng TMCP Sài Gòn - Hà Nội"),
        ("EIB", "Eximbank", "Ngân hàng TMCP Xuất Nhập khẩu Việt Nam"),
        ("MSB", "MSB", "Ngân hàng TMCP Hàng Hải Việt Nam"),
        ("OCB", "OCB", "Ngân hàng TMCP Phương Đông"),
        ("SEAB", "SeABank", "Ngân hàng TMCP Đông Nam Á"),
        ("LPB", "LPBank", "Ngân hàng TMCP Lộc Phát Việt Nam"),
        ("NAB", "NamABank", "Ngân hàng TMCP Nam Á"),
        ("ABB", "ABBANK", "Ngân hàng TMCP An Bình"),
        ("BAB", "BacABank", "Ngân hàng TMCP Bắc Á"),
        ("KLB", "KienLongBank", "Ngân hàng TMCP Kiên Long"),
        ("VAB", "VietABank", "Ngân hàng TMCP Việt Á"),
        ("PGB", "PGBank", "Ngân hàng TMCP Thịnh vượng và Phát triển"),
        ("NCB", "NCB", "Ngân hàng TMCP Quốc Dân"),
        ("BVB", "BVBank", "Ngân hàng TMCP Bản Việt"),
        ("PVCB", "PVcomBank", "Ngân hàng TMCP Đại Chúng Việt Nam"),
        ("SGICB", "SaigonBank", "Ngân hàng TMCP Sài Gòn Công Thương"),
        ("SCB", "SCB", "Ngân hàng TMCP Sài Gòn"),
        ("CAKE", "CAKE", "Ngân hàng số CAKE by VPBank"),
    )
]

BY_CODE: dict[str, Bank] = {b.code: b for b in BANKS}


def qr_bank_param(code: str) -> str:
    """Tham số ``bank`` cho qr.sepay.vn; mã lạ (cấu hình .env cũ) dùng nguyên văn."""
    bank = BY_CODE.get(code.upper())
    return bank.short_name if bank else code


def bank_name(code: str) -> str | None:
    bank = BY_CODE.get(code.upper())
    return bank.short_name if bank else None
