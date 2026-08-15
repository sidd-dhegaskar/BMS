from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.lock_client import LockClient, get_lock_client
from app.database import get_db
from app.schemas.purchase import PurchaseRequest, PurchaseResult
from app.services import purchase_service

router = APIRouter(tags=["purchase"])


@router.post("/purchase", response_model=PurchaseResult)
async def purchase(
    request: PurchaseRequest,
    db: AsyncSession = Depends(get_db),
    lock_client: LockClient = Depends(get_lock_client),
):
    return await purchase_service.purchase_ticket(db, lock_client, request)
