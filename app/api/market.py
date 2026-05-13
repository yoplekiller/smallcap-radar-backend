"""시장 지수/환율/원자재 API."""
import httpx
from fastapi import APIRouter

from app.services.market_service import get_market_overview

router = APIRouter(prefix="/market", tags=["market"])

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


@router.get("/overview")
async def market_overview():
    return await get_market_overview()


@router.get("/futures-test")
async def futures_test():
    """야간선물 API 엔드포인트 탐색용 (임시)"""
    results = {}
    async with httpx.AsyncClient(timeout=5, headers=_HEADERS) as c:
        # Yahoo Finance 후보
        for sym in ["KM%3DF", "NK%3DF", "ES%3DF", "^KS200"]:
            try:
                r = await c.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}", params={"range": "1d", "interval": "1d"})
                d = r.json()
                result = d.get("chart", {}).get("result")
                if result:
                    m = result[0]["meta"]
                    results[sym] = {"symbol": m.get("symbol"), "price": m.get("regularMarketPrice"), "name": m.get("shortName")}
                else:
                    results[sym] = {"error": str(d.get("chart", {}).get("error"))}
            except Exception as e:
                results[sym] = {"error": str(e)}
        # Naver 후보
        for code in ["KOSPI200F", "NIGHTFUT", "K200F"]:
            try:
                r = await c.get(f"https://m.stock.naver.com/api/index/{code}/basic")
                results[f"naver_{code}"] = r.json()
            except Exception as e:
                results[f"naver_{code}"] = {"error": str(e)}
    return results
