from datetime import datetime

from sqlalchemy import Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    venue: Mapped[str] = mapped_column(String, nullable=False)
    performer: Mapped[str] = mapped_column(String, nullable=False)
    date: Mapped[datetime] = mapped_column(nullable=False)
    price: Mapped[float] = mapped_column(Numeric, nullable=False)
