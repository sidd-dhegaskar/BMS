from redis.asyncio import Redis

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
    result = await redis.set(_key(seat_id), str(user_id), nx=True, ex=ttl)
    return result is True


async def release(redis: Redis, seat_id: int, user_id: int) -> bool:
    result = await redis.eval(_COMPARE_AND_DELETE, 1, _key(seat_id), str(user_id))
    return result == 1
