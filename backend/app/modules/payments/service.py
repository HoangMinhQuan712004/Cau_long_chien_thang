from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import events
from app.core.errors import BadRequest
from app.modules.auth.models import User
from app.modules.bookings import service as bookings_service
from app.modules.bookings.models import BookingStatus
from app.modules.payments.models import Payment, PaymentStatus
from app.modules.payments.schemas import ManualPaymentIn


async def record_manual_payment(
    session: AsyncSession, booking_id: int, data: ManualPaymentIn, staff: User
) -> Payment:
    """Nhân viên ghi nhận tiền mặt / chuyển khoản và xác nhận đơn (một transaction)."""
    # Khóa dòng để tránh ghi trùng khi 2 nhân viên bấm cùng lúc / đua với job hết hạn
    booking = await bookings_service.get_booking(session, booking_id, lock=True)
    if booking.status not in (BookingStatus.PENDING, BookingStatus.CONFIRMED):
        raise BadRequest("Đơn không ở trạng thái có thể thanh toán")
    was_pending = booking.status == BookingStatus.PENDING
    payment = Payment(
        booking_id=booking.id,
        method=data.method,
        status=PaymentStatus.SUCCEEDED,
        amount=data.amount if data.amount is not None else booking.total_amount,
        created_by_id=staff.id,
    )
    session.add(payment)
    if was_pending:
        bookings_service.mark_confirmed(booking)
    await session.commit()
    await session.refresh(payment)
    if was_pending:
        await events.publish(events.BOOKING_CONFIRMED, {"booking_id": booking.id})
    return payment


async def list_payments(session: AsyncSession, booking_id: int) -> list[Payment]:
    result = await session.scalars(
        select(Payment).where(Payment.booking_id == booking_id).order_by(Payment.id)
    )
    return list(result.all())


# TODO: tích hợp cổng online (PayOS / VNPay / MoMo)
#   1. create_payment_link(booking) -> tạo Payment(PENDING, provider_ref=orderCode), trả URL/QR
#   2. webhook: XÁC THỰC CHỮ KÝ theo tài liệu provider -> idempotent theo provider_ref
#      -> khóa booking, Payment SUCCEEDED + mark_confirmed trong cùng transaction
