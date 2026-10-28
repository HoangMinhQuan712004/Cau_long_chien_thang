"""Tiền về qua SePay (ADR-001 HMAC, ADR-007 áp vào lượt thanh toán online).

Hàm ở đây **không commit** – router commit (giao dịch + booking tạo ra cùng một transaction).
"""

import hashlib
import hmac
import logging
import re
import time
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import urlencode

from sqlalchemy import func, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditActor, audit
from app.core.config import settings
from app.core.errors import AppError
from app.modules.booking_engine import api as engine
from app.modules.booking_engine.dto import OnlinePaymentIn
from app.modules.payments import config
from app.modules.payments.models import BankTransaction, PaymentSettings
from app.modules.payments.schemas import BankInfo, BankTransactionOut

logger = logging.getLogger(__name__)

PROVIDER = "sepay"
CODE_RE = re.compile(r"BK\d{11}", re.IGNORECASE)
NOTE_MAX = 500


class WebhookError(Exception):
    """Lỗi xác thực / dữ liệu webhook -> router trả ``{"success": false}`` với mã HTTP này."""

    def __init__(self, status: int, reason: str):
        super().__init__(reason)
        self.status = status


# ------------------------------------------------------------------ cấu hình / QR


async def online_enabled(session: AsyncSession) -> bool:
    return (await config.load(session)).online_enabled


def qr_url(cfg: config.PaymentConfig, amount: int, pay_ref: str) -> str:
    query = urlencode(
        {"acc": cfg.account_number, "bank": cfg.qr_bank, "amount": amount, "des": pay_ref}
    )
    return f"https://qr.sepay.vn/img?{query}"


async def bank_info(session: AsyncSession, amount: int, pay_ref: str) -> BankInfo | None:
    cfg = await config.load(session)
    if cfg.missing:
        return None
    return BankInfo(
        bank_name=cfg.bank_name or cfg.bank_code or "",
        account_number=cfg.account_number,
        account_name=cfg.account_name,
        qr_url=qr_url(cfg, amount, pay_ref),
    )


# ------------------------------------------------------------------ webhook


async def verify_signature(
    session: AsyncSession, raw_body: bytes, signature: str | None, timestamp: str | None
) -> None:
    """HMAC-SHA256(secret, "{timestamp}.{raw_body}") – so sánh hằng thời gian (T-001 AC4)."""
    secret = (await config.load(session)).webhook_secret
    if not secret:
        raise WebhookError(503, "webhook secret not configured")
    if not signature or not timestamp or not timestamp.strip().isdigit():
        raise WebhookError(401, "missing or malformed signature headers")
    expected = hmac.new(
        secret.encode(), timestamp.strip().encode() + b"." + raw_body, hashlib.sha256
    ).hexdigest()
    given = signature.strip()
    if not given.lower().startswith("sha256="):
        raise WebhookError(401, "signature must be 'sha256=<hex>'")
    given = given[len("sha256=") :]
    if not hmac.compare_digest(expected.encode(), given.lower().encode()):
        raise WebhookError(401, "bad signature")
    tolerance = settings.SEPAY_TIMESTAMP_TOLERANCE_SECONDS
    if tolerance > 0 and abs(time.time() - int(timestamp)) > tolerance:
        raise WebhookError(401, "timestamp outside tolerance")


def _parse_time(value: Any) -> datetime:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=settings.tz)
    except ValueError:
        return datetime.now(settings.tz)


def extract_code(payload: dict) -> str | None:
    """Trường ``code`` (SePay tách theo mẫu BK + 11 số); null -> tìm ``BK\\d{11}`` trong nội dung,
    chỉ dùng khi đúng 1 mã khác nhau (T-008 AC20)."""
    code = payload.get("code")
    if isinstance(code, str) and CODE_RE.fullmatch(code.strip()):
        return code.strip().upper()
    found = {m.upper() for m in CODE_RE.findall(str(payload.get("content") or ""))}
    return found.pop() if len(found) == 1 else None


def _validate(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise WebhookError(400, "body must be an object")
    txn_id, kind, amount = (
        payload.get("id"),
        payload.get("transferType"),
        payload.get("transferAmount"),
    )
    if txn_id is None or str(txn_id).strip() == "" or len(str(txn_id)) > 64:
        raise WebhookError(400, "missing id")
    if kind not in ("in", "out"):
        raise WebhookError(400, "bad transferType")
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise WebhookError(400, "bad transferAmount")
    return payload


async def process_transaction(session: AsyncSession, payload: Any, provider: str = PROVIDER) -> str:
    """Ghi giao dịch (một lần theo id) rồi áp vào lượt thanh toán.

    Trả outcome, hoặc "duplicate" khi id đã ghi.
    """
    data = _validate(payload)
    txn_id = str(data["id"])
    account = str(data.get("accountNumber") or "") or None
    new_id = await session.scalar(
        insert(BankTransaction)
        .values(
            provider=provider,
            provider_txn_id=txn_id,
            transfer_type=data["transferType"],
            amount=data["transferAmount"],
            content=str(data.get("content") or "")[:2000],
            account_number=account[:30] if account else None,
            transaction_at=_parse_time(data.get("transactionDate")),
            raw=data,
            outcome="unmatched",
        )
        .on_conflict_do_nothing(index_elements=["provider", "provider_txn_id"])
        .returning(BankTransaction.id)
    )
    if new_id is None:
        logger.info("Duplicate bank transaction %s:%s ignored", provider, txn_id)
        return "duplicate"
    txn = await session.get(BankTransaction, new_id)

    receiving = (await config.load(session)).account_number
    if data["transferType"] != "in" or (account and account != receiving):
        txn.outcome = "ignored"
        return txn.outcome
    code = extract_code(data)
    txn.code = code
    if code is None:
        return txn.outcome  # unmatched
    result = await engine.apply_online_payment(
        session,
        OnlinePaymentIn(
            pay_ref=code,
            amount=txn.amount,
            transaction_at=txn.transaction_at,
            reference=f"{provider}:{txn_id}",
        ),
    )
    txn.outcome = result.outcome
    txn.refund_amount = result.refund_amount
    txn.booking_codes = result.booking_codes
    txn.pay_ref = code if result.outcome != "unmatched" else None
    await session.flush()
    if result.checkout_closed_unpaid:
        # Lượt thanh toán không thể hoàn tất: các lần trả thiếu trước đó cũng cần hoàn
        # (idempotent – mỗi giao dịch chỉ chuyển partial -> refund_needed một lần)
        await mark_expired_partials(session, code)
    logger.info("Bank transaction %s:%s -> %s", provider, txn_id, result.outcome)
    return result.outcome


async def simulate(session: AsyncSession, pay_ref: str, amount: int) -> BankTransactionOut:
    """Giả lập tiền về (chỉ dev/staging) – đi đúng đường xử lý của webhook; trả giao dịch đã ghi."""
    txn_id = f"sim-{uuid.uuid4()}"
    await process_transaction(
        session,
        {
            "id": txn_id,
            "transferType": "in",
            "transferAmount": amount,
            "code": None,
            "content": f"{pay_ref} giả lập",
            "accountNumber": (await config.load(session)).account_number,
            "transactionDate": datetime.now(settings.tz).strftime("%Y-%m-%d %H:%M:%S"),
            "gateway": "SIMULATE",
        },
    )
    txn = await session.scalar(
        select(BankTransaction).where(
            BankTransaction.provider == PROVIDER, BankTransaction.provider_txn_id == txn_id
        )
    )
    return _out(txn)


async def mark_webhook_seen(session: AsyncSession) -> None:
    """Chữ ký hợp lệ (kể cả "Gửi thử" của SePay) -> cập nhật "Lần cuối nhận thông báo" (AC10).

    Chỉ khi đã có dòng cài đặt (chưa có: đang dùng .env, không tạo dòng để khỏi đổi nguồn cấu hình).
    """
    await session.execute(
        update(PaymentSettings)
        .where(PaymentSettings.tenant_id == settings.TENANT_ID)
        .values(last_webhook_at=func.now(), updated_at=PaymentSettings.updated_at)
    )


async def mark_expired_partials(session: AsyncSession, pay_ref: str) -> int:
    """Lượt thanh toán hết hạn khi mới nhận một phần tiền -> các giao dịch đó cần hoàn."""
    result = await session.execute(
        update(BankTransaction)
        .where(BankTransaction.pay_ref == pay_ref, BankTransaction.outcome == "partial")
        .values(outcome="refund_needed", refund_amount=BankTransaction.amount)
    )
    return result.rowcount or 0


# ------------------------------------------------------------------ Tiền về cần xử lý (AC32)


def _needs_action():
    return (BankTransaction.resolved_at.is_(None)) & or_(
        BankTransaction.outcome.in_(("unmatched", "refund_needed")),
        (BankTransaction.outcome == "applied") & (BankTransaction.refund_amount > 0),
    )


def _out(t: BankTransaction) -> BankTransactionOut:
    return BankTransactionOut(
        id=t.id,
        provider=t.provider,
        provider_txn_id=t.provider_txn_id,
        received_at=t.received_at,
        transaction_at=t.transaction_at,
        amount=t.amount,
        content=t.content,
        code=t.code,
        outcome=t.outcome,
        refund_amount=t.refund_amount,
        booking_codes=list(t.booking_codes or []),
        resolved_at=t.resolved_at,
        resolved_by_label=t.resolved_by_label,
        note=t.note,
    )


async def list_transactions(
    session: AsyncSession, needs_action: bool, limit: int
) -> list[BankTransactionOut]:
    stmt = select(BankTransaction).order_by(
        BankTransaction.received_at.desc(), BankTransaction.id.desc()
    )
    if needs_action:
        stmt = stmt.where(_needs_action())
    return [_out(t) for t in await session.scalars(stmt.limit(limit))]


async def count_needs_action(session: AsyncSession) -> int:
    return await session.scalar(
        select(func.count()).select_from(BankTransaction).where(_needs_action())
    )


async def resolve(
    session: AsyncSession, txn_id: int, note: str, actor: AuditActor
) -> BankTransactionOut:
    note = note.strip()
    if not note:
        raise AppError("E-001", "Vui lòng nhập Ghi chú.", 422)
    if len(note) > NOTE_MAX:
        raise AppError("E-001", f"Ghi chú tối đa {NOTE_MAX} ký tự.", 422)
    txn = await session.scalar(
        select(BankTransaction).where(BankTransaction.id == txn_id).with_for_update()
    )
    if txn is None:
        raise AppError("E-NOT-FOUND", "Không tìm thấy giao dịch.", 404)
    if txn.resolved_at is not None:
        raise AppError("E-PAY-2", "Giao dịch đã được xử lý.", 409)
    txn.resolved_at = datetime.now(settings.tz)
    txn.resolved_by_id, txn.resolved_by_label = actor.id, actor.label
    txn.note = note
    audit(
        session,
        actor,
        "payment.bank_txn.resolve",
        "bank_transaction",
        str(txn.id),
        {"outcome": txn.outcome, "amount": txn.amount, "refund_amount": txn.refund_amount},
    )
    await session.flush()
    return _out(txn)
