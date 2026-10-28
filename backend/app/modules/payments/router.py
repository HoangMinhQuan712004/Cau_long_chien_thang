"""Webhook SePay, Tiền về cần xử lý, giả lập tiền về (dev).

Webhook là ngoại lệ có chủ đích của ADR-004: **không** cookie, **không** Origin, **không**
Idempotency-Key – xác thực bằng HMAC; chống trùng bằng UNIQUE(provider, id SePay).
"""

import json
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query, Request, status
from fastapi.responses import JSONResponse

from app.core.audit import AuditActor
from app.core.config import settings
from app.core.db import SessionDep
from app.core.errors import AppError
from app.core.idempotency import IdempotencyDep
from app.core.permissions import Perm, Principal, require
from app.modules.payments import config, service, settings_service
from app.modules.payments.banks import BANKS
from app.modules.payments.schemas import (
    BankOut,
    BankTransactionOut,
    PaymentSettingsIn,
    PaymentSettingsOut,
    ResolveIn,
    SimulateIn,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])

PaymentsViewer = Annotated[Principal, Depends(require(Perm.PAYMENTS_VIEW))]
PaymentsResolver = Annotated[Principal, Depends(require(Perm.PAYMENTS_RESOLVE))]
SettingsManager = Annotated[Principal, Depends(require(Perm.PAYMENTS_SETTINGS))]


def _result(ok: bool, status_code: int = 200) -> JSONResponse:
    return JSONResponse({"success": ok}, status_code=status_code)


@router.post("/sepay/webhook", include_in_schema=False)
async def sepay_webhook(
    request: Request,
    session: SessionDep,
    x_sepay_signature: Annotated[str | None, Header()] = None,
    x_sepay_timestamp: Annotated[str | None, Header()] = None,
):
    """SePay báo giao dịch: HMAC trên ``"{timestamp}.{raw_body}"`` (ADR-001, T-001 AC4–AC6).

    Chưa cấu hình secret -> 503; chữ ký sai -> 401; body sai -> 400; lỗi DB -> 500 (SePay gửi lại).
    Luôn trả đúng ``{"success": bool}``.
    """
    raw = await request.body()
    try:
        await service.verify_signature(session, raw, x_sepay_signature, x_sepay_timestamp)
        await service.mark_webhook_seen(session)
        await session.commit()
        try:
            payload = json.loads(raw)
        except ValueError:
            raise service.WebhookError(400, "invalid JSON") from None
        await service.process_transaction(session, payload)
    except service.WebhookError as e:
        await session.rollback()
        logger.warning("SePay webhook rejected (%s): %s", e.status, e)
        return _result(False, e.status)
    await session.commit()
    return _result(True)


@router.get("/bank-transactions", response_model=list[BankTransactionOut])
async def list_bank_transactions(
    _: PaymentsViewer,
    session: SessionDep,
    needs_action: bool = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    """Tiền về (mới nhất trước). ``needs_action=true``: chưa xử lý và cần Admin xem
    (``unmatched``, ``refund_needed``, ``applied`` có tiền thừa)."""
    return await service.list_transactions(session, needs_action, limit)


@router.post("/bank-transactions/{txn_id}/resolve", response_model=BankTransactionOut)
async def resolve_bank_transaction(
    txn_id: int,
    data: ResolveIn,
    principal: PaymentsResolver,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Đánh dấu Đã xử lý (ghi chú 1–500 ký tự, E-001); đã xử lý rồi -> 409 ``E-PAY-2``."""
    actor = AuditActor(type=principal.actor_type, id=principal.actor_id, label=principal.label)
    return await idem.run(
        session, principal.key, lambda: service.resolve(session, txn_id, data.note, actor)
    )


async def simulate_enabled() -> None:
    # Production không bao giờ bật được (Settings từ chối khởi động); cờ tắt -> như không có route
    if not settings.PAYMENTS_SIMULATE or settings.is_production:
        raise AppError("E-NOT-FOUND", "Not Found", status.HTTP_404_NOT_FOUND)


@router.post(
    "/dev/simulate",
    response_model=BankTransactionOut,
    dependencies=[Depends(simulate_enabled)],
)
async def simulate_payment(
    data: SimulateIn, principal: PaymentsResolver, idem: IdempotencyDep, session: SessionDep
):
    """Giả lập tiền về cho ``pay_ref`` (chỉ dev/staging, ``PAYMENTS_SIMULATE=true``).

    Trả giao dịch vừa ghi (``outcome``, ``refund_amount``, ``booking_codes``…).
    """
    return await idem.run(
        session,
        principal.key,
        lambda: service.simulate(session, data.pay_ref.strip(), data.amount),
    )


# ---------------------------------------------------------------- cài đặt thanh toán (T-012)


@router.get("/settings", response_model=PaymentSettingsOut)
async def get_settings(_: SettingsManager, session: SessionDep):
    """Cài đặt nhận tiền online (chỉ Admin). Khóa webhook không trả ra – chỉ 4 ký tự cuối."""
    return await settings_service.view(session)


@router.put("/settings", response_model=PaymentSettingsOut)
async def put_settings(
    data: PaymentSettingsIn,
    principal: SettingsManager,
    idem: IdempotencyDep,
    session: SessionDep,
):
    """Lưu cài đặt – luôn cần ``current_password``.

    Lỗi: 400 E-AUTH-7 (sai mật khẩu; 5 lần / 15 phút -> 429 E-SEC-5), 422 E-PAY-4 (dữ liệu),
    409 E-PAY-3 (đổi ngân hàng / số TK khi còn lượt chờ thanh toán).
    """
    actor = AuditActor(type=principal.actor_type, id=principal.actor_id, label=principal.label)
    response = await idem.run(
        session, principal.key, lambda: settings_service.save(session, data, actor)
    )
    config.clear_cache()  # sau commit: lần đọc sau lấy cấu hình mới
    return response


@router.get("/banks", response_model=list[BankOut])
async def list_banks(_: SettingsManager):
    """Danh sách ngân hàng (mã VietQR) cho ô chọn."""
    return BANKS
