import logging

from redis.asyncio import Redis

logger = logging.getLogger("lock_service")

_COMPARE_AND_DELETE = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""


def _key(seat_id: int) -> str:
    return f"ticket:{seat_id}"


async def acquire(redis: Redis, seat_id: int, user_id: int, ttl: int) -> bool:
    key = _key(seat_id)
    logger.info("SET %s %s NX EX %s", key, user_id, ttl)
    result = await redis.set(key, str(user_id), nx=True, ex=ttl)
    acquired = result is True
    if acquired:
        logger.info("  -> OK: lock acquired (key did not exist)")
    else:
        holder = await redis.get(key)
        holder_str = holder.decode() if holder else None
        logger.info("  -> nil: already locked (held by user_id=%s)", holder_str)
    return acquired


async def release(redis: Redis, seat_id: int, user_id: int) -> bool:
    key = _key(seat_id)
    logger.info(
        "EVAL compare-and-delete %s ARGV[1]=%s (caller's user_id)", key, user_id
    )
    result = await redis.eval(_COMPARE_AND_DELETE, 1, key, str(user_id))
    released = result == 1
    if released:
        logger.info("  -> 1: GET matched caller, key deleted")
    else:
        logger.info(
            "  -> 0: GET did not match caller (expired or held by someone else) — no-op"
        )
    return released
