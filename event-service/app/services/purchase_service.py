import asyncio

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.lock_client import LockAlreadyHeldError, LockClient
from app.models import Booking, Ticket
from app.schemas.purchase import PurchaseRequest, PurchaseResult

SIMULATED_PAYMENT_DELAY_SECONDS = 5


async def purchase_ticket(
    db: AsyncSession, lock_client: LockClient, request: PurchaseRequest
) -> PurchaseResult:
    try:
        await lock_client.acquire(seat_id=request.seat_id, user_id=request.user_id)
    except LockAlreadyHeldError:
        raise HTTPException(status_code=409, detail="seat already locked")

    try:
        booking = Booking(
            ticket_id=request.seat_id, user_id=request.user_id, status="pending"
        )
        db.add(booking)
        await db.flush()

        await asyncio.sleep(SIMULATED_PAYMENT_DELAY_SECONDS)

        result = await db.execute(
            update(Ticket)
            .where(
                Ticket.id == request.seat_id,
                Ticket.version == request.expected_version,
                Ticket.status == "available",
            )
            .values(status="booked", user_id=request.user_id, version=Ticket.version + 1)
        )

        booking.status = "confirmed" if result.rowcount == 1 else "failed"
        await db.commit()

        return PurchaseResult(
            booking_id=booking.id, ticket_id=request.seat_id, status=booking.status
        )
    finally:
        await lock_client.release(seat_id=request.seat_id, user_id=request.user_id)
