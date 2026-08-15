"""Seed sample events and tickets into Postgres for local development.

Usage (from event-service/):
    ./venv/Scripts/python.exe -m scripts.seed
"""

import asyncio
from datetime import datetime

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Event, Ticket

SEAT_NUMBERS = ["A1", "A2", "A3", "B1", "B2", "B3"]


async def seed():
    async with SessionLocal() as db:
        existing = await db.execute(select(Event).where(Event.name == "Drake — It's All A Blur Tour"))
        if existing.scalar_one_or_none():
            print("Drake concert already seeded, skipping.")
            return

        event = Event(
            name="Drake — It's All A Blur Tour",
            venue="Madison Square Garden",
            performer="Drake",
            date=datetime(2026, 9, 1, 20, 0),
            price=150.00,
        )
        db.add(event)
        await db.flush()  # assigns event.id

        for seat_number in SEAT_NUMBERS:
            db.add(Ticket(event_id=event.id, seat_number=seat_number, status="available"))

        await db.commit()
        print(f"Seeded event {event.id} with {len(SEAT_NUMBERS)} seats.")


if __name__ == "__main__":
    asyncio.run(seed())
