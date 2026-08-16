from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis

from app.redis_client import get_redis
from app.schemas.lock import LockRequest, UnlockRequest
from app.services import lock_service

router = APIRouter()


@router.post("/lock")
async def lock(request: LockRequest, redis: Redis = Depends(get_redis)):
    acquired = await lock_service.acquire(
        redis, request.seat_id, request.user_id, request.ttl
    )
    if not acquired:
        raise HTTPException(status_code=409, detail="seat already locked")
    return {"status": "locked"}


@router.post("/unlock")
async def unlock(request: UnlockRequest, redis: Redis = Depends(get_redis)):
    await lock_service.release(redis, request.seat_id, request.user_id)
    return {"status": "unlocked"}
