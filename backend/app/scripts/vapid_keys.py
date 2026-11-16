"""Sinh cặp khóa VAPID cho Web Push (T-076) dạng dòng ``.env``.

Chạy trên server, ghi thẳng vào tệp env – không in ra màn hình chung / board / chat:
    python -m app.scripts.vapid_keys >> .env
"""

import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate() -> tuple[str, str]:
    """(khóa công khai 65 byte, khóa riêng 32 byte) – base64url không ``=``."""
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    public = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return _b64url(public), _b64url(private)


if __name__ == "__main__":
    public, private = generate()
    print(f"VAPID_PUBLIC_KEY={public}")
    print(f"VAPID_PRIVATE_KEY={private}")
