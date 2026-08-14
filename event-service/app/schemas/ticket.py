from pydantic import BaseModel, ConfigDict


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: int
    seat_number: str
    status: str
