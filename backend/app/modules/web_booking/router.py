"""Web khách (T-008): lịch đặt sân, lượt thanh toán QR, tra cứu – **không cần đăng nhập**.

BFF ghép Hội viên + Booking engine + Thanh toán (giống ``front_desk``). Snapshot khách dựng ở
server: SĐT trùng hội viên đang hoạt động -> hồ sơ hội viên; còn lại -> hồ sơ tạm theo tên khách
nhập, **chưa tạo** hồ sơ (tạo khi tiền về – ADR-007 §7).
"""

import datetime as dt
import re
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.context import client_ip
from app.core.db import SessionDep
from app.core.errors import AppError
from app.core.idempotency import IdempotencyDep
from app.core.middleware import require_origin
from app.core.privacy import mask_phone
from app.core.ratelimit import rate_limit
from app.modules.auth import api as auth
from app.modules.booking_engine import api as engine
from app.modules.booking_engine.dto import CheckoutCreate, CheckoutView, CustomerSnapshot
from app.modules.members import api as members
from app.modules.payments import api as payments
from app.modules.web_booking.schemas import (
    CheckoutCreatedOut,
    CheckoutIn,
    CheckoutOut,
    LookupIn,
    LookupOut,
    LookupPendingOut,
    PhoneCodeIn,
    PhoneCodeSentOut,
    PhoneTokenOut,
    PhoneVerifyIn,
    WebCalendarOut,
    WebCheckoutItem,
    WebCustomer,
)

router = APIRouter(prefix="/web/booking", tags=["web-booking"])

NAME_MAX = 100
NOTE_MAX = 200
CODE_COMPACT = re.compile(r"^BK(\d{8})(\d{3})$")
METHOD_LABELS = {
    "cash": "Tiền mặt",
    "transfer": "Chuyển khoản",
    "online_transfer": "Chuyển khoản",
}


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


def _web_error(message: str) -> AppError:
    return AppError("E-WEB-1", message, 422)


async def _online_enabled(session: AsyncSession) -> bool:
    """Đủ cấu hình thanh toán **và** có kênh gửi OTP xác minh SĐT (T-013 AC27)."""
    return auth.otp_channel_ready() and await payments.online_enabled(session)


async def _require_online(session: AsyncSession) -> None:
    if not await _online_enabled(session):
        raise AppError("E-WEB-5", "Đặt online đang tạm ngưng. Vui lòng gọi hotline.", 503)


async def _checkout_out(session: AsyncSession, view: CheckoutView) -> dict:
    return {
        "status": view.status,
        "expires_at": view.expires_at,
        "server_now": view.server_now,
        "amount": view.amount,
        "paid_amount": view.paid_amount,
        "paid_at": view.paid_at,
        "pay_ref": view.pay_ref,
        "bank": await payments.bank_info(session, view.amount, view.pay_ref)
        if view.status == "pending"
        else None,
        "customer": WebCustomer(
            full_name=view.customer_name, phone_masked=mask_phone(view.customer_phone)
        ),
        "items": [WebCheckoutItem(**i.model_dump()) for i in view.items],
    }


# ------------------------------------------------------------------ lịch (AC1–AC5)


@router.get(
    "/calendar",
    response_model=WebCalendarOut,
    dependencies=[Depends(rate_limit("web.calendar", 60)), Depends(no_store)],
)
async def calendar(session: SessionDep, day: Annotated[dt.date, Query(alias="date")]):
    """Lịch đặt sân cho khách: trạng thái + giá từng ô; ngày đã qua -> 422 ``E-WEB-2``."""
    cal = await engine.public_calendar(session, day)
    return WebCalendarOut(
        **cal.model_dump(),
        online_enabled=await _online_enabled(session),
        hold_minutes=settings.ONLINE_HOLD_MINUTES,
    )


# ------------------------------------------------------------------ lượt thanh toán (AC6–AC18)


def _valid_phone(raw: str) -> str:
    phone = members.normalize_phone(raw)
    if not members.PHONE_RE.match(phone):
        raise _web_error("Số điện thoại không hợp lệ — cần đủ 10 số.")
    return phone


def _validate_customer(data: CheckoutIn) -> tuple[str, str, str | None]:
    full_name = " ".join(data.full_name.split())
    if not full_name:
        raise _web_error("Vui lòng nhập họ tên.")
    if len(full_name) > NAME_MAX:
        raise _web_error(f"Họ tên tối đa {NAME_MAX} ký tự.")
    phone = _valid_phone(data.phone)
    note = (data.note or "").strip() or None
    if note and len(note) > NOTE_MAX:
        raise _web_error(f"Ghi chú tối đa {NOTE_MAX} ký tự.")
    return full_name, phone, note


@router.post(
    "/checkouts",
    response_model=CheckoutCreatedOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[
        Depends(require_origin),
        Depends(rate_limit("web.checkout", 6, window_s=600)),
    ],
)
async def create_checkout(
    data: CheckoutIn,
    idem: IdempotencyDep,
    session: SessionDep,
    verified_phone: auth.VerifiedCustomerPhone,
):
    """Giữ chỗ 5 phút + cấp mã, trả ``token`` (một lần) để mở trang thanh toán.

    Cần ``phone_token`` của đúng SĐT (trừ khách đăng nhập có SĐT đã xác minh trùng ``phone``).
    Lỗi: E-WEB-1 (dữ liệu), E-WEB-2 (khung không đặt được), E-WEB-3 (vừa có người đặt, kèm
    ``conflicts``), E-WEB-4 (SĐT đang có lượt chờ), E-WEB-5 (đặt online tạm ngưng),
    E-WEB-8 (chưa xác minh SĐT), E-019.
    """
    await _require_online(session)
    full_name, phone, note = _validate_customer(data)
    if verified_phone != phone and not await auth.booking_phone_token_valid(
        session, data.phone_token, phone
    ):
        raise AppError("E-WEB-8", "Vui lòng xác minh số điện thoại trước khi đặt sân.", 403)

    async def run() -> CheckoutCreatedOut:
        profile = await members.find_by_phone(session, phone)
        # Hội viên Ngừng vẫn gắn vào hội viên khi đặt online (T-020 AC2 – Ngừng chỉ là nhãn)
        if profile is not None and profile.kind == "member":
            snapshot = CustomerSnapshot(
                ref_id=profile.ref,
                kind="member",
                display_name=profile.full_name,
                phone=phone,
                member_code=profile.member_code,
                tier=profile.tier,
            )
        else:
            snapshot = CustomerSnapshot(
                ref_id=profile.ref if profile else f"phone:{phone}",
                kind="temp",
                display_name=full_name,
                phone=phone,
            )
        created = await engine.create_checkout(
            session,
            CheckoutCreate(date=data.date, slots=data.slots, note=note),
            snapshot,
            settings.ONLINE_HOLD_MINUTES,
        )
        return CheckoutCreatedOut(**await _checkout_out(session, created), token=created.token)

    actor_key = f"web:{client_ip() or 'unknown'}"
    return await idem.run(session, actor_key, run, status_code=status.HTTP_201_CREATED)


@router.post(
    "/phone/request",
    response_model=PhoneCodeSentOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(require_origin)],
)
async def phone_request(data: PhoneCodeIn, session: SessionDep):
    """Gửi OTP xác minh SĐT trước khi đặt (T-013 AC25).

    Lỗi: E-WEB-1 (SĐT sai), E-WEB-5 (đặt online tạm ngưng), E-AUTH-13 (gửi quá nhiều, 429).
    """
    await _require_online(session)
    sent = await auth.send_booking_phone_code(session, _valid_phone(data.phone), client_ip())
    return PhoneCodeSentOut(resend_after=sent.resend_after, test_otp=sent.test_otp)


@router.post(
    "/phone/verify",
    response_model=PhoneTokenOut,
    dependencies=[Depends(require_origin), Depends(no_store)],
)
async def phone_verify(
    data: PhoneVerifyIn, session: SessionDep, customer_id: auth.SignedInCustomerId
):
    """Mã đúng -> ``phone_token`` (30 phút, dùng cho nhiều lượt đặt của SĐT này trong hạn).

    Khách đang đăng nhập có SĐT tài khoản trùng -> ``account_verified`` (T-013 AC40).
    Lỗi: E-WEB-1 (SĐT sai), E-AUTH-14 (sai mã, ``attempts_left``), E-AUTH-15 (mã hết hiệu lực).
    """
    token = await auth.verify_booking_phone(
        session, _valid_phone(data.phone), data.otp, customer_id
    )
    return PhoneTokenOut(
        phone_token=token.token,
        expires_at=token.expires_at,
        account_verified=token.account_verified,
    )


@router.get(
    "/checkouts/{token}",
    response_model=CheckoutOut,
    dependencies=[Depends(rate_limit("web.checkout_status", 120)), Depends(no_store)],
)
async def get_checkout(token: Annotated[str, Path(max_length=100)], session: SessionDep):
    """Trạng thái lượt thanh toán (trang hỏi mỗi 3 giây). Token sai -> 404 ``E-WEB-6``."""
    return CheckoutOut(**await _checkout_out(session, await engine.get_checkout(session, token)))


# ------------------------------------------------------------------ tra cứu (AC25–AC27)


def normalize_code(raw: str) -> str:
    """``bk20261020023`` / `` BK-20261020-023 `` -> ``BK-20261020-023``."""
    code = "".join(raw.split()).upper()
    m = CODE_COMPACT.match(code)
    return f"BK-{m.group(1)}-{m.group(2)}" if m else code


@router.post(
    "/lookup",
    response_model=LookupOut,
    dependencies=[Depends(require_origin), Depends(rate_limit("web.lookup", 10))],
)
async def lookup(data: LookupIn, session: SessionDep):
    """Tra cứu theo mã booking + SĐT. Sai mã hay sai SĐT -> cùng 404 ``E-WEB-7``."""
    result = await engine.lookup(
        session, normalize_code(data.code), members.normalize_phone(data.phone)
    )
    pending = None
    if result.pending is not None:
        pending = LookupPendingOut(
            **result.pending.model_dump(),
            bank=await payments.bank_info(session, result.pending.amount, result.pending.pay_ref),
        )
    return LookupOut(
        code=result.code,
        status=result.status,
        resource_name=result.resource_name,
        play_date=result.play_date,
        start_time=result.start_time,
        end_time=result.end_time,
        hours=result.hours,
        customer_name=result.customer_name,
        phone_masked=mask_phone(result.customer_phone),
        amount=result.amount,
        payment_method_label=METHOD_LABELS.get(result.payment_method or ""),
        paid_at=result.paid_at,
        pending=pending,
    )
