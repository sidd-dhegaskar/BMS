import asyncio
import logging

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.lock_client import LockAlreadyHeldError, LockClient
from app.models import Booking, Ticket
from app.schemas.purchase import PurchaseRequest, PurchaseResult

logger = logging.getLogger("purchase_service")

SIMULATED_PAYMENT_DELAY_SECONDS = 5


async def purchase_ticket(
    db: AsyncSession, lock_client: LockClient, request: PurchaseRequest
) -> PurchaseResult:
    logger.info(
        "POST /purchase  seat_id=%s user_id=%s expected_version=%s",
        request.seat_id,
        request.user_id,
        request.expected_version,
    )

    logger.info("-> lock_client.acquire seat_id=%s (calls Lock Service POST /lock)", request.seat_id)
    try:
        await lock_client.acquire(seat_id=request.seat_id, user_id=request.user_id)
    except LockAlreadyHeldError:
        logger.info("<- 409: Redis lock rejected before Postgres was touched\n")
        raise HTTPException(status_code=409, detail="seat already locked")
    logger.info("<- lock acquired, proceeding to Postgres")

    try:
        booking = Booking(
            ticket_id=request.seat_id, user_id=request.user_id, status="pending"
        )
        db.add(booking)
        await db.flush()
        logger.info("INSERT bookings id=%s status=pending", booking.id)

        logger.info("simulating payment delay (%ss)...", SIMULATED_PAYMENT_DELAY_SECONDS)
        await asyncio.sleep(SIMULATED_PAYMENT_DELAY_SECONDS)

        logger.info(
            "UPDATE tickets SET status='booked', version=version+1 "
            "WHERE id=%s AND version=%s AND status='available'",
            request.seat_id,
            request.expected_version,
        )
        result = await db.execute(
            update(Ticket)
            .where(
                Ticket.id == request.seat_id,
                Ticket.version == request.expected_version,
                Ticket.status == "available",
            )
            .values(status="booked", user_id=request.user_id, version=Ticket.version + 1)
        )
        logger.info(
            "  -> %s row(s) affected (%s)",
            result.rowcount,
            "won the race" if result.rowcount == 1 else "lost the race: version was stale",
        )

        booking.status = "confirmed" if result.rowcount == 1 else "failed"
        await db.commit()
        logger.info("UPDATE bookings id=%s status=%s (committed)", booking.id, booking.status)

        return PurchaseResult(
            booking_id=booking.id, ticket_id=request.seat_id, status=booking.status
        )
    finally:
        logger.info("-> lock_client.release seat_id=%s (calls Lock Service POST /unlock)", request.seat_id)
        await lock_client.release(seat_id=request.seat_id, user_id=request.user_id)
        logger.info("<- 200 purchase complete\n")
