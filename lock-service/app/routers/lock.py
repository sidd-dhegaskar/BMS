import logging

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis

from app.redis_client import get_redis
from app.schemas.lock import LockRequest, UnlockRequest
from app.services import lock_service

logger = logging.getLogger("lock_service")

router = APIRouter()


@router.post("/lock")
async def lock(request: LockRequest, redis: Redis = Depends(get_redis)):
    logger.info(
        "POST /lock  seat_id=%s user_id=%s ttl=%s",
        request.seat_id,
        request.user_id,
        request.ttl,
    )
    acquired = await lock_service.acquire(
        redis, request.seat_id, request.user_id, request.ttl
    )
    if not acquired:
        logger.info("<- 409 seat already locked\n")
        raise HTTPException(status_code=409, detail="seat already locked")
    logger.info("<- 200 locked\n")
    return {"status": "locked"}


@router.post("/unlock")
async def unlock(request: UnlockRequest, redis: Redis = Depends(get_redis)):
    logger.info(
        "POST /unlock  seat_id=%s user_id=%s", request.seat_id, request.user_id
    )
    await lock_service.release(redis, request.seat_id, request.user_id)
    logger.info("<- 200 unlocked\n")
    return {"status": "unlocked"}
