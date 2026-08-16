from pydantic import BaseModel

from app.config import settings


class LockRequest(BaseModel):
    seat_id: int
    user_id: int
    ttl: int = settings.default_ttl_seconds


class UnlockRequest(BaseModel):
    seat_id: int
    user_id: int
