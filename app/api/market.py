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
    """KRX 야간선물 API 탐색용 (임시)"""
    today = datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%d")
    results = {}

    async with httpx.AsyncClient(timeout=10) as c:
        # ── KRX POST API 후보 ─────────────────────────────────────────────
        krx_candidates = [
            ("bld1_NFUT", {"bld": "dbms/MDC/STAT/standard/MDCSTAT02901", "locale": "ko_KR", "mktId": "NFUT", "trdDd": today}),
            ("bld2_KNX",  {"bld": "dbms/MDC/STAT/standard/MDCSTAT02901", "locale": "ko_KR", "mktId": "KNX",  "trdDd": today}),
            ("bld3_NFUT", {"bld": "dbms/MDC/STAT/standard/MDCSTAT02401", "locale": "ko_KR", "mktId": "NFUT", "trdDd": today}),
            ("bld4_NFUT", {"bld": "dbms/MDC/STAT/standard/MDCSTAT02001", "locale": "ko_KR", "mktId": "NFUT", "trdDd": today}),
            ("bld5_NFUT", {"bld": "dbms/MDC/STAT/standard/MDCSTAT034",   "locale": "ko_KR", "mktId": "NFUT", "trdDd": today}),
            ("bld6_KNX",  {"bld": "dbms/MDC/STAT/standard/MDCSTAT034",   "locale": "ko_KR", "mktId": "KNX",  "trdDd": today}),
        ]
        for label, payload in krx_candidates:
            try:
                r = await c.post(
                    "https://data.krx.co.kr/comm/bldAttendant/getJsonData.cmd",
                    data=payload,
                    headers=_KRX_HEADERS,
                )
                results[label] = {"status": r.status_code, "body": r.text[:500]}
            except Exception as e:
                results[label] = {"error": str(e)}

        # ── Naver 야간선물 후보 ───────────────────────────────────────────
        naver_codes = ["K2NF", "K200NF", "NKOSPI200F", "K200F2", "KNF"]
        for code in naver_codes:
            try:
                r = await c.get(f"https://m.stock.naver.com/api/index/{code}/basic", headers=_HEADERS, timeout=5)
                results[f"naver_{code}"] = {"status": r.status_code, "body": r.text[:300]}
            except Exception as e:
                results[f"naver_{code}"] = {"error": str(e)}

        # ── KRX 야간선물 직접 페이지 크롤링 시도 ─────────────────────────
        try:
            r = await c.get(
                "https://data.krx.co.kr/contents/MDC/STAT/standard/MDCSTAT02901.cmd",
                headers=_KRX_HEADERS,
            )
            results["krx_page"] = {"status": r.status_code, "body": r.text[:300]}
        except Exception as e:
            results["krx_page"] = {"error": str(e)}

    return {"date": today, "results": results}
