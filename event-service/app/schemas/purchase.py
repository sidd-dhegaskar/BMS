from pydantic import BaseModel


class PurchaseRequest(BaseModel):
    seat_id: int
    user_id: int
    expected_version: int


class PurchaseResult(BaseModel):
    booking_id: int
    ticket_id: int
    status: str
