from fastapi import APIRouter, HTTPException
from typing import Any
import httpx
from app.services.dart_service import (
    fetch_recent_disclosures, fetch_company_info, search_disclosures,
    fetch_earnings_disclosures, fetch_company_disclosures_by_code
)
from app.services.market_cap_service import filter_small_cap_disclosures, fetch_stock_price
from app.services.ai_service import analyze_disclosure, analyze_earnings_disclosure
from app.services.news_service import fetch_stock_news

router = APIRouter(prefix="/disclosures", tags=["공시"])


@router.get("/recent")
async def get_recent_disclosures(days: int = 1, small_cap_only: bool = False):
    """최근 공시 목록 조회 — 캐시된 AI 분석 결과를 자동으로 포함합니다."""
    from app.services.analysis_cache import get as cache_get
    try:
        disclosures = await fetch_recent_disclosures(days)
        if small_cap_only:
            disclosures = await filter_small_cap_disclosures(disclosures)
        # 캐시에 분석 결과가 있으면 즉시 삽입 (Groq 호출 없음)
        for d in disclosures:
            rcept = d.get("rcept_no", "")
            if rcept and not d.get("ai"):
                cached = cache_get(rcept)
                if cached:
                    d["ai"] = cached
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


@router.get("/companies/search")
async def search_companies(q: str):
    """회사명으로 회사 목록 조회 — 공시 없어도 검색 가능 (포트폴리오 종목 추가용)"""
    from app.services.corp_code_service import find_corp_codes
    if not q.strip():
        raise HTTPException(status_code=400, detail="검색어를 입력하세요")
    try:
        corps = await find_corp_codes(q.strip())
        return {"count": len(corps), "data": corps}
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
        result = await analyze_earnings_disclosure(disclosure, profit_data or {})
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


@router.get("/consensus/{stock_code}")
async def get_consensus(stock_code: str):
    """Naver Finance 증권사 컨센서스 영업이익 조회"""
    from app.services.comparison_service import fetch_naver_consensus
    data = await fetch_naver_consensus(stock_code)
    if not data:
        raise HTTPException(status_code=404, detail="컨센서스 데이터를 찾을 수 없습니다.")
    return data


@router.post("/earnings-shock")
async def earnings_shock_endpoint(body: dict[str, Any]):
    """어닝쇼크 판정: 실제 영업이익(억원) vs Naver 컨센서스 비교

    Body: { stock_code: str, actual_억: float }
    """
    stock_code = body.get("stock_code")
    actual_억 = body.get("actual_억")

    if not stock_code or actual_억 is None:
        raise HTTPException(status_code=400, detail="stock_code, actual_억 필요")

    from app.services.comparison_service import fetch_naver_consensus, detect_earnings_shock
    consensus = await fetch_naver_consensus(stock_code)

    if not consensus:
        return {
            "verdict": "비교 불가",
            "verdict_en": "unavailable",
            "diff_pct": None,
            "comment": "컨센서스 데이터가 없습니다.",
            "consensus": None,
        }

    shock = detect_earnings_shock(float(actual_억), consensus["operating_profit_억"])
    return {**shock, "consensus": consensus}


@router.post("/market-cap-compare")
async def market_cap_compare_endpoint(body: dict[str, Any]):
    """공시 금액과 시가총액 비율 계산

    Body: { stock_code: str, amount_억: float }
    """
    stock_code = body.get("stock_code")
    amount_억 = body.get("amount_억")

    if not stock_code or amount_억 is None:
        raise HTTPException(status_code=400, detail="stock_code, amount_억 필요")

    from app.services.market_cap_service import fetch_stock_price
    from app.services.comparison_service import build_market_cap_comment

    info = await fetch_stock_price(stock_code)
    if not info or not info.get("market_cap"):
        raise HTTPException(status_code=404, detail="시가총액 정보를 가져올 수 없습니다.")

    market_cap_억 = round(info["market_cap"] / 1e8, 1)
    result = build_market_cap_comment(float(amount_억), market_cap_억)
    return {**result, "market_cap_억_현재": market_cap_억}


@router.get("/price-history/{stock_code}")
async def get_price_history(stock_code: str, count: int = 30):
    """네이버 금융 일별 종가 조회 (포트폴리오 차트용)"""
    url = (
        f"https://fchart.stock.naver.com/sise.nhn"
        f"?symbol={stock_code}&timeframe=day&count={count}&requestType=0"
    )
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
        data = []
        for line in r.text.splitlines():
            line = line.strip()
            if not line.startswith("<item"):
                continue
            raw = line.replace('<item data="', "").replace('"/>', "").strip()
            parts = raw.split("|")
            if len(parts) >= 5 and parts[4]:
                data.append({"date": parts[0], "close": int(parts[4])})
        return {"stock_code": stock_code, "data": data}
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


@router.get("/earnings")
async def get_earnings_disclosures(days: int = 30):
    """영업실적 공시 전용 — 거래소공시(I) 중 '실적' 키워드만 조회, AI 캐시 포함"""
    from app.services.analysis_cache import get as cache_get
    try:
        disclosures = await fetch_earnings_disclosures(days)
        for d in disclosures:
            rcept = d.get("rcept_no", "")
            if rcept and not d.get("ai"):
                cached = cache_get(f"earnings:{rcept}") or cache_get(rcept)
                if cached:
                    d["ai"] = cached
        return {"count": len(disclosures), "data": disclosures}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/calendar")
async def get_calendar_disclosures(month: str | None = None):
    """캘린더용 공시 조회 — 특정 월(YYYYMM) 또는 당월, 최대 2페이지(200건)

    반환: 날짜별 그룹 { "20260510": [...], ... }
    """
    from datetime import date, timedelta
    from app.services.analysis_cache import get as cache_get

    today = date.today()
    if month and len(month) == 6:
        y, m = int(month[:4]), int(month[4:])
        bgn = date(y, m, 1)
        if m == 12:
            end = date(y + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(y, m + 1, 1) - timedelta(days=1)
    else:
        bgn = date(today.year, today.month, 1)
        end = today

    bgn_str = bgn.strftime("%Y%m%d")
    end_str = min(end, today).strftime("%Y%m%d")

    try:
        all_items: list[dict] = []
        async with httpx.AsyncClient(timeout=10) as client:
            for page in range(1, 2):  # 1페이지(100건)만
                r = await client.get(
                    "https://opendart.fss.or.kr/api/list.json",
                    params={
                        "crtfc_key": __import__("os").getenv("DART_API_KEY"),
                        "bgn_de": bgn_str,
                        "end_de": end_str,
                        "last_reprt_at": "N",
                        "page_no": page,
                        "page_count": 100,
                    },
                )
                r.raise_for_status()
                data = r.json()
                if data.get("status") != "000":
                    break
                items = data.get("list", [])
                for d in items:
                    rcept = d.get("rcept_no", "")
                    if rcept:
                        cached = cache_get(rcept)
                        if cached:
                            d["ai"] = cached
                all_items.extend(items)
                if len(items) < 100:
                    break

        # 날짜별 그룹
        grouped: dict[str, list] = {}
        for item in all_items:
            dt = item.get("rcept_dt", "")
            if dt:
                grouped.setdefault(dt, []).append(item)

        return {"month": month or today.strftime("%Y%m"), "data": grouped}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/company/{corp_code}/history")
async def get_company_history(corp_code: str, days: int = 90):
    """특정 회사의 최근 N일 공시 이력 (캐시된 AI 분석 포함)"""
    from app.services.analysis_cache import get as cache_get
    try:
        disclosures = await fetch_company_disclosures_by_code(corp_code, days)
        for d in disclosures:
            rcept = d.get("rcept_no", "")
            if rcept:
                cached = cache_get(rcept)
                if cached:
                    d["ai"] = cached
        return {"count": len(disclosures), "data": disclosures}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
