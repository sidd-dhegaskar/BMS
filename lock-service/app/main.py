import logging

from fastapi import Depends, FastAPI
from redis.asyncio import Redis

from app.redis_client import get_redis
from app.routers import lock

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(title="Lock Service")

app.include_router(lock.router)


@app.get("/health")
async def health(redis: Redis = Depends(get_redis)):
    await redis.ping()
    return {"status": "ok"}
