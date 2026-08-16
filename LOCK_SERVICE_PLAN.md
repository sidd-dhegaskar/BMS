# Lock Service — Build Plan

Companion to [ARCHITECTURE.md](ARCHITECTURE.md) and [EVENT_SERVICE.md](EVENT_SERVICE.md). This is a forward-looking plan for the not-yet-built Lock Service — written before implementation, to be checked against once it's done.

---

## Scope, per ARCHITECTURE.md

- Internal-only REST API — no client-facing endpoints, only called by the Event Service.
- Owns Redis exclusively. No Postgres, no durable state.
- Two endpoints: `POST /lock`, `POST /unlock`.
- Locking primitive: `SET ticket:{id} user_id NX EX <ttl>` — single-seat only. Multi-seat all-or-nothing locking is explicitly deferred to v1.
- Unlock is a **compare-and-delete** (decided 2026-08-15, see ARCHITECTURE.md's v0 scope section): a small Lua script that only deletes the Redis key if its stored value still matches the caller's `user_id`. This closes the race where a stale `/unlock` call (arriving after TTL expiry and a different user's re-lock) would otherwise delete an unrelated active lock. It does not change the double-sell guarantee — Postgres OCC in the Event Service already provides that — it only protects lock ownership.
- Deliberately dumb: no knowledge of bookings, payments, event data, or OCC.

## The fixed contract (already defined by the caller)

[event-service/app/clients/lock_client.py](event-service/app/clients/lock_client.py) already exists and dictates the exact request/response shape the Lock Service must implement — this isn't a free design choice, it's matching an existing consumer:

```python
# POST /lock — request body
{"seat_id": int, "user_id": int, "ttl": int}
# Response: 200 on success, 409 if already locked (LockClient checks status_code == 409 specifically)

# POST /unlock — request body
{"seat_id": int, "user_id": int}
# Response: 200 (LockClient calls response.raise_for_status(), so any 2xx is fine)
```

---

## Directory structure

Mirrors [event-service](event-service/)'s layout for consistency, minus the layers that don't apply (no `models/`, no `alembic/` — nothing durable to migrate):

```
lock-service/
  app/
    schemas/
      lock.py            # LockRequest, UnlockRequest (Pydantic)
    routers/
      lock.py              # POST /lock, POST /unlock — thin HTTP layer
    services/
      lock_service.py        # acquire() / release() — the actual Redis calls
    redis_client.py              # Depends()-based Redis connection, mirrors database.py's get_db()
    config.py                      # Settings: redis_url, default_ttl_seconds
    main.py                          # FastAPI app, routes included, /health
  requirements.txt
  venv/
```

---

## Step-by-step

**1. Scaffold + venv + install**
`python -m venv venv`, then install `fastapi`, `uvicorn[standard]`, `redis` (the `redis-py` async client), `pydantic-settings`. Freeze to `requirements.txt` immediately after.

**2. `config.py`**
```python
class Settings(BaseSettings):
    redis_url: str = "redis://localhost:6379"
    default_ttl_seconds: int = 60
```

**3. `redis_client.py` — connection dependency**
A single shared `redis.asyncio.Redis` instance (`redis-py`'s async client pools connections internally), exposed via a `get_redis()` function used as a FastAPI dependency — same pattern as Event Service's `get_db()`.

**4. `schemas/lock.py`**
```python
class LockRequest(BaseModel):
    seat_id: int
    user_id: int
    ttl: int = 60

class UnlockRequest(BaseModel):
    seat_id: int
    user_id: int
```

**5. `services/lock_service.py` — the actual Redis logic**

`acquire`:
```python
async def acquire(redis, seat_id: int, user_id: int, ttl: int) -> bool:
    result = await redis.set(f"ticket:{seat_id}", str(user_id), nx=True, ex=ttl)
    return result is True
```

`release` — compare-and-delete via Lua, run through `redis.eval()` for atomicity (a plain `GET` then `DEL` would reopen the same kind of race the script is meant to close):
```python
_COMPARE_AND_DELETE = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
"""

async def release(redis, seat_id: int, user_id: int) -> bool:
    result = await redis.eval(_COMPARE_AND_DELETE, 1, f"ticket:{seat_id}", str(user_id))
    return result == 1
```
`release` returning `False` (lock wasn't held by this caller, or already gone) is not an error — it's treated as a no-op, matching the semantics: "release my lock if I still have it."

**6. `routers/lock.py`**
```python
@router.post("/lock")
async def lock(request: LockRequest, redis = Depends(get_redis)):
    acquired = await lock_service.acquire(redis, request.seat_id, request.user_id, request.ttl)
    if not acquired:
        raise HTTPException(status_code=409, detail="seat already locked")
    return {"status": "locked"}

@router.post("/unlock")
async def unlock(request: UnlockRequest, redis = Depends(get_redis)):
    await lock_service.release(redis, request.seat_id, request.user_id)
    return {"status": "unlocked"}
```

**7. `main.py`**
FastAPI app, include the router, `/health` that also pings Redis (`await redis.ping()`) so the health check validates the one dependency this service actually has — not just "the process is up."

**8. Port**
Runs on **8001** — [event-service/app/config.py](event-service/app/config.py) already defaults `lock_service_url` to `http://localhost:8001`, so no config changes needed on the Event Service side.

**9. Verification plan**
- Start Redis (already running via `docker compose`), start Lock Service on 8001.
- Direct tests against Lock Service:
  - Lock seat 5 as user A → expect `200`.
  - Lock seat 5 again as user B → expect `409`.
  - Unlock seat 5 as user B (wrong owner) → expect `200`, but seat should *still* be locked (compare-and-delete no-ops).
  - Unlock seat 5 as user A (correct owner) → expect `200`, seat now free.
  - Lock seat 5 as user B again → expect `200` (proves the unlock actually cleared it).
- Then start Event Service on 8000 and run the full `POST /purchase` flow against a seeded seat (from [event-service/scripts/seed.py](event-service/scripts/seed.py)) — confirm it now completes end-to-end instead of failing at `lock_client.acquire()`.

**10. Docs**
Add a row for `lock-service` to [requirements.md](requirements.md) (already has a placeholder table for it). Once built and verified, write a `LOCK_SERVICE.md` retrospective doc mirroring [EVENT_SERVICE.md](EVENT_SERVICE.md)'s structure.

---

## Out of scope for this build (explicitly deferred, per ARCHITECTURE.md)

- Multi-seat all-or-nothing Lua locking.
- Full fencing tokens (monotonic token scheme) — compare-and-delete solves the narrow stale-unlock race but is not a general fencing mechanism.
- Redis merged into `GET /seats`.
- Load testing.

---

## Redis concepts, in depth (for explaining this design, e.g. in an interview)

### `SET key value NX EX ttl` is one atomic command, not three

Redis executes commands single-threaded, so `SET ... NX EX ...` collapses "check if the key exists" and "set it with an expiry" into one atomic step — no window for another client to interleave. This is the reason Redis works as a distributed lock primitive at all; it's the simplified core of Redlock.

Contrast with doing it as separate calls:
- `EXISTS` then `SET` → classic TOCTOU race: two clients can both see "absent" and both proceed to set.
- `SET` then a separate `EXPIRE` → if the process dies in between, the lock has no TTL and never releases.

`SET NX EX` avoids both failure modes in one round trip.

### The lock is a lease, not a mutex

A mutex is held until explicitly released. This lock auto-expires after `ttl` seconds whether or not `/unlock` is ever called — a lease. That's a deliberate tradeoff: it trades perfect mutual exclusion for crash-safety. If the Event Service process dies mid-checkout, a classic mutex leaks forever and the seat is stuck; a lease self-heals after `ttl` seconds. The cost of that tradeoff is the stale-unlock race below.

### The stale-unlock race, walked through

1. User A locks seat 5. TTL = 60s.
2. A's checkout stalls (e.g. slow payment step) past 60s. Redis auto-expires the key.
3. User B locks seat 5 — succeeds, because the key is gone.
4. A's stalled request finally wakes up and does its cleanup: `POST /unlock` for seat 5.
5. If unlock were a plain `DEL ticket:5`, it would delete **B's active lock** — a lock A no longer owns.

That's a correctness bug purely in the locking layer, independent of Postgres. Fix: compare-and-delete, only delete if the stored value still equals the caller's `user_id`.

### Why compare-and-delete has to be a Lua script, not client-side `GET` + `DEL`

A client-side `GET` then conditional `DEL` reopens the identical race — B could re-lock in the gap between the `GET` and the `DEL`. It has to be atomic, executed *inside* Redis as one unit. Redis guarantees a Lua script (`EVAL`) runs to completion with no other command interleaved — the same single-threaded guarantee that makes `SET NX` safe, generalized to a custom read-then-conditionally-write op:

```lua
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
```

General pattern worth stating: any time you need read-modify-write semantics against Redis, plain sequential client calls are never safe — you need a single atomic command, a Lua script, or `WATCH`/`MULTI`/`EXEC`.

### Why this still isn't full fencing — and why that's fine here

Compare-and-delete fixes the *unlock*-side race but not a subtler *acquire*-side one: if A's request is so stalled it's still writing to Postgres after B has already locked and is also writing, nothing at the Redis layer stops that. Real fencing (Chubby-style, per Martin Kleppmann's Redlock critique) hands out a monotonically increasing token with each lock grant, and the protected resource rejects any write carrying a token older than the last one it saw.

This system gets the equivalent for free: Postgres's `tickets.version` column **is** a fencing token in every way that matters, just living in Postgres instead of Redis — the actual state mutation is the point that needs protecting, and OCC already protects it. Worth saying explicitly: *"we don't need separate fencing tokens because the OCC version column already serves that purpose where it counts."*

### Why two layers (Redis + Postgres) and not just one

| Layer | Speed | Guarantee |
|---|---|---|
| Redis `SET NX EX` | fast, in-memory, cheap to reject | stops *most* concurrent attempts before they touch Postgres |
| Postgres OCC (`UPDATE ... WHERE version = ?`) | slower, disk-backed | the actual correctness guarantee — atomic conditional write |

Redis alone isn't sufficient because of the TTL-expiry race above. Postgres alone would be correct but wasteful — every concurrent request for a hot seat would hit the database and only one would win, which doesn't scale under thundering-herd load (e.g. a popular on-sale). Redis is a cheap fast-path filter; Postgres is the source of truth. Same shape as a bloom filter in front of a database, or cache-aside.

### Why `release()` returning `False` is a no-op, not an error

`False` means either the lock already expired or someone else now holds it — in both cases "my job here is done." The router always returns `200` regardless of the internal True/False. This keeps `/unlock` idempotent: a caller retrying an unlock shouldn't get punished for it.

### Why multi-seat locking (deferred) is structurally harder, not just more code

You can't loop `SET NX` per seat from the client — if seat 3 succeeds and seat 7 fails, you're now in a partial-acquisition state and need to roll back seat 3's lock, which is itself race-prone. The correct approach is a single Lua script taking all seat keys as `KEYS`, checking all are free, and only then setting all of them atomically in one round trip — the same "collapse check-and-act into one op" principle as `SET NX`, generalized to N keys.

### Postgres OCC walkthrough — concretely, with numbers

Seat 5 starts at `version = 3, status = 'available'`. Users A, B, C all read that row around the same time and each proceeds with `expected_version = 3` (this is the "optimistic" part — nobody takes a lock at read time). Suppose all three reach the OCC write (e.g. via the TTL-expiry race):

```sql
UPDATE tickets
SET status = 'booked', user_id = ?, version = version + 1
WHERE id = 5 AND version = 3 AND status = 'available'
```

- **A's write executes first** (Postgres serializes writes to the same row). `WHERE version = 3` matches, 1 row affected, commits → `version` becomes `4`.
- **B's write executes next.** Row now has `version = 4`; B's `WHERE version = 3` matches zero rows. Not an error — just a predicate that no longer holds. `0 rows affected` → app treats this as "lost the race," marks `bookings.status = 'failed'`.
- **C's write** — same outcome, `0 rows affected`, `failed`.

No explicit locking (`SELECT ... FOR UPDATE`, manual coordination) is needed — a single `UPDATE` is atomic per-row in Postgres, and that atomicity alone gives mutual exclusion. Even if two transactions "arrive" at the same instant, the database serializes the actual row mutation; the second to physically execute already sees the first's committed `version`. Under the hood (MVCC), the second transaction briefly blocks on the first's row lock, then re-evaluates its `WHERE` against the now-committed row and finds it stale — invisible to app code, which just sees `0`.

Sharp edge worth flagging: OCC failure is **not a thrown exception**, it's a silent `0` in the affected-row count. The app must explicitly check that count and branch on it — forgetting the check makes a lost race look identical to a successful no-op, a silent correctness bug.
