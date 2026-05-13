"""시장 지수/환율/원자재 API."""
from fastapi import APIRouter

from app.services.market_service import get_market_overview

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/overview")
async def market_overview():
    return await get_market_overview()
