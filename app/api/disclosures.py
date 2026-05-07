from fastapi import APIRouter, HTTPException
from typing import Any
import httpx
from app.services.dart_service import fetch_recent_disclosures, fetch_company_info
from app.services.market_cap_service import filter_small_cap_disclosures
from app.services.ai_service import analyze_disclosure

router = APIRouter(prefix="/disclosures", tags=["공시"])


@router.get("/recent")
async def get_recent_disclosures(days: int = 1, small_cap_only: bool = False):
    """최근 공시 목록 조회 (small_cap_only=true: 시총 3000억 미만만)"""
    try:
        disclosures = await fetch_recent_disclosures(days)
        if small_cap_only:
            disclosures = await filter_small_cap_disclosures(disclosures)
        return {"count": len(disclosures), "data": disclosures}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze")
async def analyze_one(disclosure: dict[str, Any]):
    """공시 데이터를 직접 받아 AI 분석"""
    try:
        result = await analyze_disclosure(disclosure)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug/naver/{ticker}")
async def debug_naver(ticker: str):
    """Naver API 응답 원본 확인용"""
    url = f"https://m.stock.naver.com/api/stock/{ticker}/integration"
    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url, headers=headers)
        return response.json()


@router.get("/company/{corp_code}")
async def get_company_info(corp_code: str):
    """기업 기본 정보 조회"""
    try:
        info = await fetch_company_info(corp_code)
        return info
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
