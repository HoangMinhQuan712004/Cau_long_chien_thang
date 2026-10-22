from fastapi import APIRouter, status

from app.modules.auth.deps import SessionDep, StaffUser
from app.modules.payments import service
from app.modules.payments.schemas import ManualPaymentIn, PaymentOut

admin_router = APIRouter(prefix="/admin/bookings", tags=["admin: payments"])


@admin_router.get("/{booking_id}/payments", response_model=list[PaymentOut])
async def list_payments(booking_id: int, _: StaffUser, session: SessionDep):
    return await service.list_payments(session, booking_id)


@admin_router.post(
    "/{booking_id}/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED
)
async def record_payment(
    booking_id: int, data: ManualPaymentIn, staff: StaffUser, session: SessionDep
):
    return await service.record_manual_payment(session, booking_id, data, staff)
