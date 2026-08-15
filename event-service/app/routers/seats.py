from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.ticket import TicketOut
from app.services import seat_service

router = APIRouter(tags=["seats"])


@router.get("/events/{event_id}/seats", response_model=list[TicketOut])
async def get_seats(event_id: int, db: AsyncSession = Depends(get_db)):
    return await seat_service.list_seats(db, event_id)
