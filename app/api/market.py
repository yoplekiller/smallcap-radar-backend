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
    """KRX 야간선물 API 탐색용 (임시) - 3차 시도"""
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    results = {}

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as c:
        # ── 1. Naver PC Finance API (fchart / polling) ────────────────────
        for code in ["101S9000", "101S6000"]:
            try:
                r = await c.get(
                    f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count=1&requestType=0",
                    headers=_HEADERS, timeout=5
                )
                results[f"fchart_{code}"] = {"status": r.status_code, "body": r.text[:300]}
            except Exception as e:
                results[f"fchart_{code}"] = {"error": str(e)}

        # ── 2. Naver polling realtime API ─────────────────────────────────
        for code in ["101S9000", "101S6000"]:
            try:
                r = await c.get(
                    f"https://polling.finance.naver.com/api/realtime.naver?query=SERVICE_ITEM:{code}",
                    headers=_HEADERS, timeout=5
                )
                results[f"polling_{code}"] = {"status": r.status_code, "body": r.text[:400]}
            except Exception as e:
                results[f"polling_{code}"] = {"error": str(e)}

        # ── 3. Naver domestic futures total page ──────────────────────────
        try:
            r = await c.get(
                "https://m.stock.naver.com/domestic/futures/101S9000/total",
                headers=_HEADERS, timeout=5
            )
            results["naver_domestic_101S9000"] = {"status": r.status_code, "body": r.text[:300]}
        except Exception as e:
            results["naver_domestic_101S9000"] = {"error": str(e)}

        # ── 4. KRX 공개 bld 코드 (KOSPI 지수) 로그인 없이 되는지 확인 ─────
        try:
            session_r = await c.get("https://data.krx.co.kr/", headers=_KRX_HEADERS)
            cookies = dict(session_r.cookies)
            pub_payload = {
                "bld": "dbms/MDC/STAT/standard/MDCSTAT00101",
                "locale": "ko_KR",
                "trdDd": today,
            }
            r2 = await c.post(
                "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                data=pub_payload,
                headers=_KRX_HEADERS,
                cookies=cookies,
            )
            results["krx_public_index"] = {"status": r2.status_code, "body": r2.text[:400]}
        except Exception as e:
            results["krx_public_index"] = {"error": str(e)}

        # ── 5. 한경닷컴 야간선물 ──────────────────────────────────────────
        try:
            r = await c.get(
                "https://finance.hankyung.com/svc/api/quote/domestic/index?category=fut&code=101S9000",
                headers=_HEADERS, timeout=5,
            )
            results["hankyung_101S9000"] = {"status": r.status_code, "body": r.text[:300]}
        except Exception as e:
            results["hankyung_101S9000"] = {"error": str(e)}

        # ── 6. Yahoo Finance KOSPI200 선물 후보 재확인 ────────────────────
        for sym in ["%5EKS200", "NK%3DF", "2KF%3DF", "KOSPIF"]:
            try:
                r = await c.get(
                    f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                    params={"range": "5d", "interval": "1d"},
                    headers={**_HEADERS, "Accept": "application/json"},
                    timeout=8,
                )
                d = r.json()
                meta = (d.get("chart", {}).get("result") or [{}])[0].get("meta", {})
                err = d.get("chart", {}).get("error")
                results[f"yahoo_{sym}"] = {
                    "price": meta.get("regularMarketPrice"),
                    "name": meta.get("shortName"),
                    "exchange": meta.get("exchangeName"),
                    "error": err,
                }
            except Exception as e:
                results[f"yahoo_{sym}"] = {"error": str(e)}

    return {"date": today, "results": results}
