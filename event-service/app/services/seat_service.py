from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Ticket


async def list_seats(db: AsyncSession, event_id: int) -> list[Ticket]:
    result = await db.execute(select(Ticket).where(Ticket.event_id == event_id))
    return list(result.scalars().all())
