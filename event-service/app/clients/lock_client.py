import httpx

from app.config import settings


class LockAlreadyHeldError(Exception):
    pass


class LockClient:
    def __init__(self, base_url: str = settings.lock_service_url):
        self._base_url = base_url

    async def acquire(self, seat_id: int, user_id: int) -> None:
        async with httpx.AsyncClient(base_url=self._base_url) as client:
            response = await client.post(
                "/lock",
                json={
                    "seat_id": seat_id,
                    "user_id": user_id,
                    "ttl": settings.lock_ttl_seconds,
                },
            )
        if response.status_code == 409:
            raise LockAlreadyHeldError(f"seat {seat_id} already locked")
        response.raise_for_status()

    async def release(self, seat_id: int, user_id: int) -> None:
        async with httpx.AsyncClient(base_url=self._base_url) as client:
            response = await client.post(
                "/unlock", json={"seat_id": seat_id, "user_id": user_id}
            )
        response.raise_for_status()


def get_lock_client() -> LockClient:
    return LockClient()
