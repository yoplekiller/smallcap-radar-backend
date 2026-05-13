"""시장 지수/환율/원자재 API."""
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter

from app.services.market_service import get_market_overview

router = APIRouter(prefix="/market", tags=["market"])

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_KRX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://data.krx.co.kr/",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": "https://data.krx.co.kr",
}


@router.get("/overview")
async def market_overview():
    return await get_market_overview()


@router.get("/krx-night-test")
async def krx_night_test():
    """KRX 야간선물 API 탐색용 (임시) - 2차 시도"""
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    results = {}

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        # ── 1. KRX 세션 쿠키 먼저 획득 후 POST ───────────────────────────
        try:
            session_r = await c.get("https://data.krx.co.kr/", headers=_KRX_HEADERS)
            cookies = dict(session_r.cookies)
            results["krx_session"] = {"status": session_r.status_code, "cookies": list(cookies.keys())}

            payload = {
                "bld": "dbms/MDC/STAT/standard/MDCSTAT02901",
                "locale": "ko_KR",
                "mktId": "NFUT",
                "trdDd": today,
                "share": "1",
                "money": "1",
                "csvxls_isNo": "false",
            }
            r2 = await c.post(
                "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                data=payload,
                headers=_KRX_HEADERS,
                cookies=cookies,
            )
            results["krx_session_post"] = {"status": r2.status_code, "body": r2.text[:500]}
        except Exception as e:
            results["krx_session"] = {"error": str(e)}

        # ── 2. Naver stock 엔드포인트 (index 아닌 stock으로) ──────────────
        for code in ["101S9000", "101S6000", "K200F"]:
            try:
                r = await c.get(f"https://m.stock.naver.com/api/stock/{code}/basic", headers=_HEADERS, timeout=5)
                results[f"naver_stock_{code}"] = {"status": r.status_code, "body": r.text[:300]}
            except Exception as e:
                results[f"naver_stock_{code}"] = {"error": str(e)}

        # ── 3. Naver 선물 전용 API ────────────────────────────────────────
        try:
            r = await c.get(
                "https://m.stock.naver.com/api/futures/101S9000/basic",
                headers=_HEADERS, timeout=5
            )
            results["naver_futures_101S9000"] = {"status": r.status_code, "body": r.text[:300]}
        except Exception as e:
            results["naver_futures_101S9000"] = {"error": str(e)}

        # ── 4. 네이버 야간선물 검색 ───────────────────────────────────────
        try:
            r = await c.get(
                "https://m.stock.naver.com/api/search/rapid?query=코스피200야간선물&target=index,stock",
                headers=_HEADERS, timeout=5
            )
            results["naver_search"] = {"status": r.status_code, "body": r.text[:500]}
        except Exception as e:
            results["naver_search"] = {"error": str(e)}

        # ── 5. 다음(카카오) 파이낸스 ─────────────────────────────────────
        for code in ["K200F", "KOSPI200F", "K2NF"]:
            try:
                r = await c.get(
                    f"https://finance.daum.net/api/quotes/FUT:{code}",
                    headers={**_HEADERS, "Referer": "https://finance.daum.net/"},
                    timeout=5,
                )
                results[f"daum_{code}"] = {"status": r.status_code, "body": r.text[:300]}
            except Exception as e:
                results[f"daum_{code}"] = {"error": str(e)}

        # ── 6. Yahoo Finance ^KS200 상세 확인 ────────────────────────────
        try:
            r = await c.get(
                "https://query1.finance.yahoo.com/v8/finance/chart/%5EKS200",
                params={"range": "1d", "interval": "5m"},
                headers={**_HEADERS, "Accept": "application/json"},
                timeout=8,
            )
            d = r.json()
            meta = (d.get("chart", {}).get("result") or [{}])[0].get("meta", {})
            results["yahoo_KS200"] = {
                "symbol": meta.get("symbol"),
                "price": meta.get("regularMarketPrice"),
                "prev": meta.get("chartPreviousClose"),
                "name": meta.get("shortName"),
                "exchangeName": meta.get("exchangeName"),
            }
        except Exception as e:
            results["yahoo_KS200"] = {"error": str(e)}

    return {"date": today, "results": results}
