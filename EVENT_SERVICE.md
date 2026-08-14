# Event Service — Implementation Notes

Companion to [ARCHITECTURE.md](ARCHITECTURE.md). That doc describes the intended design; this one documents what's actually been built for the Event Service, in the order a request flows through it.

---

## 1. Local infrastructure — [docker-compose.yml](docker-compose.yml)

Two containers: Postgres (owned by Event Service) and Redis (owned by the future Lock Service).

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: ticketing
      POSTGRES_PASSWORD: ticketing
      POSTGRES_DB: ticketing
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data

  redis:
    image: redis:7
    ports:
      - "6379:6379"
```

The `POSTGRES_DB` env var makes the official Postgres image auto-create the `ticketing` database and `ticketing` user on first boot — no manual `CREATE DATABASE` step needed. Start with `docker compose up -d`.

---

## 2. Data layer — SQLAlchemy models ([event-service/app/models/](event-service/app/models/))

These define the actual Postgres tables. `Base` is the shared declarative base all models inherit from:

```python
# app/models/base.py
class Base(DeclarativeBase):
    pass
```

`Ticket` is where the OCC (optimistic concurrency control) `version` column lives, and the `UNIQUE` constraint that stops duplicate seats at the DB level:

```python
# app/models/ticket.py
class Ticket(Base):
    __tablename__ = "tickets"
    __table_args__ = (UniqueConstraint("event_id", "seat_number"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[int] = mapped_column(ForeignKey("events.id"), nullable=False)
    seat_number: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="available")
    user_id: Mapped[int | None] = mapped_column(nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, default=0)
```

`Booking` is the append-only attempt log, with Postgres-side timestamps (`func.now()` runs as SQL, not Python, so it's accurate regardless of app-server clock drift):

```python
# app/models/booking.py
created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
updated_at: Mapped[datetime] = mapped_column(
    server_default=func.now(), onupdate=func.now(), nullable=False
)
```

These models are never sent over the API directly — see schemas (§5) for the boundary between DB shape and API shape.

---

## 3. Migrations — Alembic ([event-service/alembic/](event-service/alembic/))

`env.py` was customized from the default template in two ways:

```python
# pulls in our model metadata so autogenerate can diff against it
from app.config import settings
from app.models import Base

# Alembic runs migrations synchronously, so the app's async DB URL
# gets its driver swapped for the sync psycopg2 one
sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
config.set_main_option("sqlalchemy.url", sync_url)

target_metadata = Base.metadata
```

`alembic revision --autogenerate` diffed the models against the (empty) database and generated one migration, [695565197bc3_create_events_tickets_bookings_tables.py](event-service/alembic/versions/695565197bc3_create_events_tickets_bookings_tables.py), containing the `CREATE TABLE` statements for all three tables plus FK and unique constraints. `alembic upgrade head` applied it — confirmed via `\dt` showing `events`, `tickets`, `bookings`, and Alembic's own `alembic_version` tracking table.

Autogenerate only **writes** the migration file by diffing model metadata against the DB's current schema; nothing is applied to Postgres until `upgrade head` actually runs it.

---

## 4. Config — [event-service/app/config.py](event-service/app/config.py)

Centralizes settings, loaded from env vars or a `.env` file (gitignored):

```python
class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://ticketing:ticketing@localhost:5432/ticketing"
    lock_service_url: str = "http://localhost:8001"
    lock_ttl_seconds: int = 60
```

---

## 5. Schemas — Pydantic ([event-service/app/schemas/](event-service/app/schemas/))

Request/response *shapes* over HTTP, deliberately kept separate from the SQLAlchemy models so internal fields never leak into API responses:

```python
# app/schemas/ticket.py
class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)  # lets Pydantic read from a Ticket ORM object
    id: int
    event_id: int
    seat_number: str
    status: str
```

`TicketOut` has no `user_id` or `version` — those are internal/PII-adjacent and OCC plumbing, not something `GET /seats` should expose.

```python
# app/schemas/purchase.py
class PurchaseRequest(BaseModel):
    seat_id: int
    user_id: int
    expected_version: int   # client must supply the version it last read

class PurchaseResult(BaseModel):
    booking_id: int
    ticket_id: int
    status: str
```

---

## 6. DB session dependency — [event-service/app/database.py](event-service/app/database.py)

```python
engine = create_async_engine(settings.database_url)
SessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db():
    async with SessionLocal() as session:
        yield session
```

This is a FastAPI dependency (used as `Depends(get_db)` in routers). The `yield` pattern means FastAPI opens a session before the request handler runs and guarantees it's closed after — even if the handler raises.

---

## 7. Lock Service client — [event-service/app/clients/lock_client.py](event-service/app/clients/lock_client.py)

The Lock Service doesn't exist yet, but this is the HTTP contract the Event Service expects from it:

```python
class LockClient:
    async def acquire(self, seat_id: int, user_id: int) -> None:
        async with httpx.AsyncClient(base_url=self._base_url) as client:
            response = await client.post("/lock", json={
                "seat_id": seat_id, "user_id": user_id, "ttl": settings.lock_ttl_seconds,
            })
        if response.status_code == 409:
            raise LockAlreadyHeldError(f"seat {seat_id} already locked")
        response.raise_for_status()

    async def release(self, seat_id: int, user_id: int) -> None:
        async with httpx.AsyncClient(base_url=self._base_url) as client:
            response = await client.post("/unlock", json={"seat_id": seat_id, "user_id": user_id})
        response.raise_for_status()
```

`get_lock_client()` is a factory function used as a dependency — in tests, this can be overridden with a fake client instead of mocking `httpx` internals.

---

## 8. Services — business logic ([event-service/app/services/](event-service/app/services/))

`seat_service.py` is a straightforward read:

```python
async def list_seats(db: AsyncSession, event_id: int) -> list[Ticket]:
    result = await db.execute(select(Ticket).where(Ticket.event_id == event_id))
    return list(result.scalars().all())
```

`purchase_service.py` implements the full `POST /purchase` sequence diagram from ARCHITECTURE.md:

```python
async def purchase_ticket(db, lock_client, request: PurchaseRequest) -> PurchaseResult:
    # 1. Acquire the Redis lock via the Lock Service — fast rejection path
    try:
        await lock_client.acquire(seat_id=request.seat_id, user_id=request.user_id)
    except LockAlreadyHeldError:
        raise HTTPException(status_code=409, detail="seat already locked")

    try:
        # 2. Log the attempt as 'pending' BEFORE the payment delay
        booking = Booking(ticket_id=request.seat_id, user_id=request.user_id, status="pending")
        db.add(booking)
        await db.flush()  # assigns booking.id without committing yet

        # 3. Simulated payment delay — the window where a TTL-expiry race could happen
        await asyncio.sleep(SIMULATED_PAYMENT_DELAY_SECONDS)

        # 4. The atomic OCC write — single conditional UPDATE, not SELECT-then-UPDATE
        result = await db.execute(
            update(Ticket)
            .where(
                Ticket.id == request.seat_id,
                Ticket.version == request.expected_version,
                Ticket.status == "available",
            )
            .values(status="booked", user_id=request.user_id, version=Ticket.version + 1)
        )

        # 5. rowcount tells us who won the race
        booking.status = "confirmed" if result.rowcount == 1 else "failed"
        await db.commit()

        return PurchaseResult(booking_id=booking.id, ticket_id=request.seat_id, status=booking.status)
    finally:
        # 6. ALWAYS release the lock — success or OCC failure
        await lock_client.release(seat_id=request.seat_id, user_id=request.user_id)
```

The `finally` block is the direct code expression of an explicit requirement in ARCHITECTURE.md:

> "The Redis lock is released either way — success or OCC failure — so a failed purchase never leaves a seat stuck for the full TTL."

---

## 9. Routers — HTTP layer ([event-service/app/routers/](event-service/app/routers/))

Routers do no logic themselves — they parse input via the schema, call the service, and let FastAPI serialize the response:

```python
# app/routers/purchase.py
@router.post("/purchase", response_model=PurchaseResult)
async def purchase(
    request: PurchaseRequest,
    db: AsyncSession = Depends(get_db),
    lock_client: LockClient = Depends(get_lock_client),
):
    return await purchase_service.purchase_ticket(db, lock_client, request)
```

```python
# app/routers/seats.py
@router.get("/events/{event_id}/seats", response_model=list[TicketOut])
async def get_seats(event_id: int, db: AsyncSession = Depends(get_db)):
    return await seat_service.list_seats(db, event_id)
```

`response_model=` does two things: validates/filters the output against the schema (so extra fields returned by the service get stripped, not leaked), and feeds FastAPI's auto-generated OpenAPI docs at `/docs`.

---

## 10. App entrypoint — [event-service/app/main.py](event-service/app/main.py)

```python
app = FastAPI(title="Event Service")
app.include_router(seats.router)
app.include_router(purchase.router)

@app.get("/health")
async def health():
    return {"status": "ok"}
```

---

## Directory layout

```
event-service/
  alembic/               # migration environment + versions/
  app/
    models/              # SQLAlchemy — Event, Ticket, Booking (DB shape)
    schemas/             # Pydantic — TicketOut, PurchaseRequest, PurchaseResult (API shape)
    clients/             # LockClient — HTTP wrapper for the (future) Lock Service
    services/            # seat_service, purchase_service — business logic
    routers/              # GET /events/{id}/seats, POST /purchase — thin HTTP layer
    database.py            # Depends()-based async DB session
    config.py                # Settings (DB URL, Lock Service URL, TTL)
    main.py                    # FastAPI app, routers included, /health
  requirements.txt              # pinned dependencies
```

This is the standard FastAPI "bigger applications" layout — routers stay thin, business logic lives in services, and Pydantic schemas keep the DB model shape from leaking into the API contract. See [requirements.md](requirements.md) for the full dependency list and why each one was added.

---

## What's been verified

Ran `uvicorn app.main:app --port 8000` against the live Postgres container:

- `GET /health` → `200 {"status": "ok"}`
- `GET /events/1/seats` → `200 []` — correct, since no events/tickets are seeded yet, but proves the full path (router → service → SQLAlchemy → asyncpg → Postgres) works end-to-end.
- `POST /purchase` — **not** verified successfully. It depends on the Lock Service, which doesn't exist yet, so it currently fails at `lock_client.acquire()`. This is expected given current scope, not a defect.

## What's explicitly not done yet

- **Lock Service** — doesn't exist. `/purchase` can't complete until it does.
- **No data seeded** — `events`/`tickets` tables are empty; nothing to exercise `/purchase` against even with the Lock Service in place.
- **No event/ticket creation endpoint** — v0 scope per ARCHITECTURE.md doesn't call for one explicitly; seeding currently requires raw SQL or a script.
- **No automated tests** — nothing under `event-service/tests/` yet.
- **`GET /seats` doesn't merge Redis state** — deferred to v1 per ARCHITECTURE.md; reads Postgres only.
