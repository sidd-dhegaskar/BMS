# Requirements Tracking

Tracks the direct libraries used across services and why. Each service has its own `requirements.txt` (installed via `pip install -r requirements.txt` in that service's virtualenv) — this file is the human-readable summary; the `.txt` files are the pinned, installable source of truth.

## event-service

Owns Postgres. See [event-service/requirements.txt](event-service/requirements.txt) for the full pinned dependency tree (incl. transitive deps).

| Library | Version | Purpose |
|---|---|---|
| fastapi | 0.141.1 | REST API framework |
| uvicorn[standard] | 0.52.1 | ASGI server to run FastAPI |
| sqlalchemy | 2.0.51 | ORM / table definitions for `events`, `tickets`, `bookings` |
| asyncpg | 0.31.0 | Async Postgres driver, used by the app at runtime |
| psycopg2-binary | 2.9.12 | Sync Postgres driver, used by Alembic only (migrations run synchronously) |
| alembic | 1.19.1 | Database migrations |
| pydantic-settings | 2.15.0 | Loads config (e.g. `DATABASE_URL`) from env vars / `.env` |
| httpx | 0.28.1 | Async HTTP client used to call the Lock Service (`/lock`, `/unlock`) |

## lock-service

Owns Redis. Not yet scaffolded.

| Library | Version | Purpose |
|---|---|---|
| fastapi | TBD | REST API framework |
| uvicorn[standard] | TBD | ASGI server to run FastAPI |
| redis (redis-py, async) | TBD | Redis client for `SET NX EX` locking |

---

**Convention:** when adding a new direct dependency to a service, install it in that service's venv, re-run `pip freeze > requirements.txt` in that service's directory, and add a row to the matching table above with the reason it was added.
