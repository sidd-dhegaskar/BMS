import logging

from fastapi import FastAPI

from app.routers import purchase, seats

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

app = FastAPI(title="Event Service")

app.include_router(seats.router)
app.include_router(purchase.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
