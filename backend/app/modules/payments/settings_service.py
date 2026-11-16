"""Trang Cài đặt → Thanh toán online (T-012): xem / lưu tài khoản nhận tiền, khóa SePay.

Lưu luôn đòi **nhập lại mật khẩu** (chống kẻ chiếm phiên đổi số tài khoản), 5 lần sai / 15 phút
-> khóa lưu. Đổi ngân hàng / số TK khi còn lượt chờ thanh toán -> chặn (khách đã quét QR cũ).
Hàm ở đây **không commit**.
"""

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import ratelimit
from app.core.audit import AuditActor, audit
from app.core.config import settings
from app.core.errors import AppError
from app.modules.auth import api as auth
from app.modules.booking_engine import api as engine
from app.modules.payments import config
from app.modules.payments.banks import BY_CODE
from app.modules.payments.models import PaymentSettings
from app.modules.payments.schemas import PaymentSettingsIn, PaymentSettingsOut

PAY_CODE_HINT = "BK + 11 chữ số"
PASSWORD_SCOPE = "payments.settings.password"
PASSWORD_LIMIT = 5
PASSWORD_WINDOW = 15 * 60
ACCOUNT_RE = re.compile(r"^\d{6,20}$")
NAME_RE = re.compile(r"^[A-Z ]{2,50}$")


def _field_error(message: str) -> AppError:
    return AppError("E-PAY-4", message, 422)


def webhook_url() -> str:
    site = (settings.ALLOWED_ORIGINS[0] if settings.ALLOWED_ORIGINS else "").rstrip("/")
    return f"{site}{settings.API_PREFIX}/payments/sepay/webhook"


def normalize_account_name(raw: str) -> str:
    """Viết hoa, bỏ dấu, gộp khoảng trắng: "  Nguyễn  Văn Đạt " -> "NGUYEN VAN DAT"."""
    text = raw.replace("đ", "d").replace("Đ", "D")
    text = "".join(
        ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn"
    )
    return " ".join(text.upper().split())


async def view(session: AsyncSession) -> PaymentSettingsOut:
    cfg = await config.load(session, fresh=True)
    return PaymentSettingsOut(
        bank_code=cfg.bank_code,
        bank_name=cfg.bank_name,
        account_number=cfg.account_number,
        account_name=cfg.account_name,
        online_toggle=cfg.online_toggle,
        online_enabled=cfg.online_enabled,
        missing=cfg.missing,
        secret_set=bool(cfg.webhook_secret),
        secret_last4=cfg.secret_last4 if cfg.webhook_secret else None,
        webhook_url=webhook_url(),
        pay_code_hint=PAY_CODE_HINT,
        last_webhook_at=cfg.last_webhook_at,
        updated_at=cfg.updated_at,
        updated_by_label=cfg.updated_by_label,
        pending_checkouts=await engine.count_pending_checkouts(session),
        simulate_enabled=bool(settings.PAYMENTS_SIMULATE) and not settings.is_production,
    )


def _validate(data: PaymentSettingsIn) -> tuple[str, str, str, str | None]:
    bank_code = data.bank_code.strip().upper()
    if bank_code not in BY_CODE:
        raise _field_error("Chọn ngân hàng.")
    account = data.account_number.strip()
    if not ACCOUNT_RE.match(account):
        raise _field_error("Số tài khoản gồm 6–20 chữ số.")
    name = normalize_account_name(data.account_name)
    if not NAME_RE.match(name):
        raise _field_error("Tên chủ tài khoản 2–50 ký tự, không dấu.")
    secret = data.webhook_secret
    if secret is not None and not 16 <= len(secret) <= 128:
        raise _field_error("Khóa bí mật 16–128 ký tự.")
    return bank_code, account, name, secret


async def _check_password(session: AsyncSession, actor: AuditActor, password: str) -> None:
    key = f"{actor.type}:{actor.id}"
    retry_after = await ratelimit.failures_exceeded(
        PASSWORD_SCOPE, key, PASSWORD_LIMIT, PASSWORD_WINDOW
    )
    if retry_after is not None:
        raise ratelimit.too_many(retry_after)
    if actor.id is None or not await auth.check_password(session, actor.id, password):
        await ratelimit.record_failure(PASSWORD_SCOPE, key, PASSWORD_WINDOW)
        raise AppError("E-AUTH-7", "Mật khẩu không đúng.", 400)


def _last4(value: str | None) -> str | None:
    return value[-4:] if value else None


async def save(
    session: AsyncSession, data: PaymentSettingsIn, actor: AuditActor
) -> PaymentSettingsOut:
    await _check_password(session, actor, data.current_password)
    bank_code, account, name, secret = _validate(data)

    row = await session.scalar(
        select(PaymentSettings)
        .where(PaymentSettings.tenant_id == settings.TENANT_ID)
        .with_for_update()
    )
    current = await config.load(session, fresh=True)
    account_changed = (bank_code, account) != (
        (current.bank_code or "").upper(),
        current.account_number or "",
    )
    if account_changed:
        pending = await engine.count_pending_checkouts(session)
        if pending:
            raise AppError(
                "E-PAY-3",
                f"Đang có {pending} lượt chờ thanh toán. Tắt Nhận đặt online, đợi các lượt hết "
                "hạn (tối đa 6 phút) rồi đổi tài khoản.",
                409,
            )
    # Có dòng = nguồn duy nhất: dòng mới không kế thừa khóa của .env
    has_secret = secret is not None or bool(row is not None and row.webhook_secret_enc)
    if data.online_toggle and not has_secret:
        raise _field_error("Chưa đủ thông tin để bật đặt online.")

    old = config.from_row(row) if row is not None else current
    if row is None:
        row = PaymentSettings(tenant_id=settings.TENANT_ID)
        session.add(row)
    row.bank_code, row.bank_name = bank_code, BY_CODE[bank_code].short_name
    row.account_number, row.account_name = account, name
    row.online_toggle = data.online_toggle
    if secret is not None:
        row.webhook_secret_enc = config.encrypt_secret(secret)
        row.secret_last4 = secret[-4:]
    row.updated_by_id, row.updated_by_label = actor.id, actor.label

    changes: dict = {}
    if (old.bank_code or "").upper() != bank_code:
        changes["bank_code"] = {"from": old.bank_code, "to": bank_code}
    if old.account_number != account:
        # Chỉ 4 số cuối – không ghi số tài khoản đầy đủ vào nhật ký
        changes["account_number_last4"] = {
            "from": _last4(old.account_number),
            "to": _last4(account),
        }
    if old.account_name != name:
        changes["account_name"] = {"from": old.account_name, "to": name}
    if old.online_toggle != data.online_toggle or current.source == "env":
        changes["online_toggle"] = {"from": old.online_toggle, "to": data.online_toggle}
    if secret is not None:
        changes["webhook_secret"] = "đã đổi"
    if current.source == "env":
        changes["source"] = "chuyển từ .env sang cài đặt trên trang"
    audit(session, actor, "payments.settings.update", "payment_settings", None, changes)
    await session.flush()
    config.clear_cache()
    return await view(session)
