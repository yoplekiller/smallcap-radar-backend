from fastapi import APIRouter, HTTPException
from typing import Any
import httpx
from app.services.dart_service import fetch_recent_disclosures, fetch_company_info, search_disclosures, fetch_earnings_disclosures
from app.services.market_cap_service import filter_small_cap_disclosures, fetch_stock_price
from app.services.ai_service import analyze_disclosure, analyze_news, analyze_earnings_disclosure
from app.services.news_service import fetch_stock_news

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


@router.get("/search")
async def search(q: str, days: int = 30):
    """회사명으로 공시 검색"""
    if not q.strip():
        raise HTTPException(status_code=400, detail="검색어를 입력하세요")
    try:
        results = await search_disclosures(q.strip(), days)
        return {"count": len(results), "data": results}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-earnings")
async def analyze_earnings_endpoint(disclosure: dict[str, Any]):
    """영업실적 공시: 전년동기 영업이익 조회 후 AI 분석 (맑음/흐림)"""
    corp_code = disclosure.get("corp_code")
    rcept_dt = disclosure.get("rcept_dt")

    if not corp_code or not rcept_dt:
        raise HTTPException(status_code=400, detail="corp_code, rcept_dt 필요")

    try:
        from app.services.dart_service import fetch_operating_profit

        profit_data = await fetch_operating_profit(corp_code, rcept_dt)
        if not profit_data:
            result = await analyze_disclosure(disclosure)
            return result

        result = await analyze_earnings_disclosure(disclosure, profit_data)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/analyze-news")
async def analyze_news_endpoint(body: dict[str, Any]):
    """뉴스 헤드라인 목록 AI 감성 분석"""
    titles = body.get("titles", [])
    corp_name = body.get("corp_name", "")
    try:
        result = await analyze_news(titles, corp_name)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/prices")
async def get_stock_prices(tickers: str):
    """여러 종목 가격 일괄 조회 (tickers=005930,000660,...)"""
    from app.services.market_cap_service import _fetch_stock_infos
    ticker_list = [t.strip() for t in tickers.split(",") if t.strip()]
    if not ticker_list:
        return {}
    try:
        info_map = await _fetch_stock_infos(ticker_list)
        return {t: info for t, info in info_map.items() if info}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/price/{stock_code}")
async def get_stock_price(stock_code: str):
    """종목 현재가/등락률/시총 조회"""
    try:
        info = await fetch_stock_price(stock_code)
        if not info:
            raise HTTPException(status_code=404, detail="가격 정보를 가져올 수 없습니다.")
        return info
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/news/{stock_code}")
async def get_stock_news(stock_code: str, limit: int = 5):
    """종목 관련 최신 뉴스 조회"""
    try:
        news = await fetch_stock_news(stock_code, limit)
        return {"stock_code": stock_code, "news": news}
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
