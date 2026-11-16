"""Giao dịch ngân hàng báo về từ cổng thanh toán (SePay) – schema ``payments`` (ADR-001, ADR-007).

Không FK sang module khác: liên kết với lượt thanh toán của booking engine qua ``pay_ref`` (chuỗi).
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    LargeBinary,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SCHEMA = "payments"
OUTCOMES = ("applied", "partial", "refund_needed", "unmatched", "ignored")


class BankTransaction(Base):
    __tablename__ = "bank_transaction"
    __table_args__ = (
        # Cùng id SePay gửi lại (retry / replay) -> không ghi trùng, không cộng tiền lần hai
        UniqueConstraint("provider", "provider_txn_id"),
        CheckConstraint(
            "outcome IN ('applied', 'partial', 'refund_needed', 'unmatched', 'ignored')",
            name="outcome",
        ),
        CheckConstraint("refund_amount >= 0", name="refund_non_negative"),
        Index("ix_bank_transaction_outcome_resolved_at", "outcome", "resolved_at"),
        Index("ix_bank_transaction_pay_ref", "pay_ref"),
        {"schema": SCHEMA},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    provider: Mapped[str] = mapped_column(String(20))
    provider_txn_id: Mapped[str] = mapped_column(String(64))
    transfer_type: Mapped[str] = mapped_column(String(10))
    amount: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, server_default=text("''"))
    code: Mapped[str | None] = mapped_column(String(30))
    account_number: Mapped[str | None] = mapped_column(String(30))
    transaction_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    raw: Mapped[dict[str, Any]] = mapped_column(JSONB)
    outcome: Mapped[str] = mapped_column(String(20))
    pay_ref: Mapped[str | None] = mapped_column(String(20))
    booking_codes: Mapped[list[str]] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    refund_amount: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by_id: Mapped[int | None] = mapped_column(BigInteger)
    resolved_by_label: Mapped[str | None] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(String(500))


class PaymentSettings(Base):
    """Cài đặt nhận tiền online do Admin nhập (T-012) – 1 dòng / tenant.

    Có dòng -> nguồn duy nhất (không trộn với ``SEPAY_*`` của .env); chưa có dòng -> dùng .env.
    Khóa webhook chỉ lưu dạng mã hóa (Fernet, ``PAYMENTS_ENCRYPTION_KEY``) + 4 ký tự cuối.
    """

    __tablename__ = "settings"
    __table_args__ = {"schema": SCHEMA}

    tenant_id: Mapped[int] = mapped_column(SmallInteger, primary_key=True, autoincrement=False)
    bank_code: Mapped[str | None] = mapped_column(String(20))
    bank_name: Mapped[str | None] = mapped_column(String(100))
    account_number: Mapped[str | None] = mapped_column(String(20))
    account_name: Mapped[str | None] = mapped_column(String(50))
    online_toggle: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    webhook_secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    secret_last4: Mapped[str | None] = mapped_column(String(4))
    last_webhook_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by_id: Mapped[int | None] = mapped_column(BigInteger)
    updated_by_label: Mapped[str | None] = mapped_column(String(100))
