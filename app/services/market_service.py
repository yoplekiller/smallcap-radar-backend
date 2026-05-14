"""시장 지수/환율/원자재/시장 분위기 데이터 서비스."""
import asyncio
import time
from typing import Any

import httpx

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

_cache: dict[str, Any] = {}
_CACHE_TTL = 60  # 60초


def _cached(key: str, value: Any) -> Any:
    _cache[key] = {"data": value, "ts": time.time()}
    return value


def _get_cache(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _CACHE_TTL:
        return entry["data"]
    return None


# ── 네이버 국내 지수 ─────────────────────────────────────────────────────────

async def _fetch_naver_index(client: httpx.AsyncClient, code: str, name: str) -> dict:
    try:
        r = await client.get(
            f"https://m.stock.naver.com/api/index/{code}/basic",
            headers=_HEADERS, timeout=5
        )
        d = r.json()
        price = float(d.get("closePrice", "0").replace(",", ""))
        change = float(d.get("compareToPreviousClosePrice", "0").replace(",", ""))
        pct = float(d.get("fluctuationsRatio", "0"))
        direction = d.get("compareToPreviousPrice", {}).get("code", "")
        if direction == "5":  # 하락
            change = -abs(change)
            pct = -abs(pct)
        return {"name": name, "value": price, "change": change, "change_pct": pct}
    except Exception:
        return {"name": name, "value": None, "change": None, "change_pct": None}


# ── Yahoo Finance (해외 지수/원자재/환율) ─────────────────────────────────────

async def _fetch_yahoo(client: httpx.AsyncClient, symbol: str, name: str) -> dict:
    try:
        r = await client.get(
            f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
            params={"range": "2d", "interval": "1d"},
            headers={**_HEADERS, "Accept": "application/json"},
            timeout=8
        )
        data = r.json()
        meta = data["chart"]["result"][0]["meta"]
        price = meta.get("regularMarketPrice") or meta.get("previousClose", 0)
        prev = meta.get("chartPreviousClose") or meta.get("previousClose", price)
        change = round(price - prev, 4)
        change_pct = round(change / prev * 100, 2) if prev else 0
        return {"name": name, "value": round(price, 2), "change": round(change, 2), "change_pct": change_pct}
    except Exception:
        return {"name": name, "value": None, "change": None, "change_pct": None}


# ── 네이버 거래대금 TOP5 ─────────────────────────────────────────────────────

async def _fetch_top_volume(client: httpx.AsyncClient) -> list[dict]:
    try:
        results = []
        for market in ["KOSPI", "KOSDAQ"]:
            r = await client.get(
                f"https://m.stock.naver.com/api/stocks/trading-volume",
                params={"market": market, "count": 5},
                headers=_HEADERS, timeout=5
            )
            for item in r.json().get("list", [])[:3]:
                results.append({
                    "name": item.get("stockName") or item.get("name", ""),
                    "code": item.get("itemCode") or item.get("code", ""),
                    "market": market,
                    "change_pct": float(item.get("fluctuationsRatio", 0)),
                    "volume_억": round(float(item.get("accumulatedTradingValue", 0)) / 1e8, 0),
                })
        return sorted(results, key=lambda x: x["volume_억"], reverse=True)[:5]
    except Exception:
        return []


# ── 네이버 상한가/하한가/외국인 ──────────────────────────────────────────────

async def _fetch_market_breadth(client: httpx.AsyncClient) -> dict:
    try:
        r = await client.get(
            "https://m.stock.naver.com/api/stocks/market-chart",
            params={"market": "KOSPI"},
            headers=_HEADERS, timeout=5
        )
        d = r.json()
        return {
            "upper_limit": d.get("upperLimitCount", 0),
            "lower_limit": d.get("lowerLimitCount", 0),
            "foreign_net_kospi": d.get("foreignNetBuy", None),
        }
    except Exception:
        pass

    # 폴백: 네이버 시장 현황 API
    try:
        r = await client.get(
            "https://m.stock.naver.com/api/index/KOSPI/basic",
            headers=_HEADERS, timeout=5
        )
        d = r.json()
        return {
            "upper_limit": d.get("upperLimitCount"),
            "lower_limit": d.get("lowerLimitCount"),
            "foreign_net_kospi": None,
        }
    except Exception:
        return {"upper_limit": None, "lower_limit": None, "foreign_net_kospi": None}


# ── 공개 API ─────────────────────────────────────────────────────────────────

async def get_market_overview() -> dict:
    cached = _get_cache("overview")
    if cached:
        return cached

    async with httpx.AsyncClient() as client:
        (
            kospi, kosdaq,
            nasdaq, sp500, vix,
            gold, wti,
            usd_krw, jpy_krw,
            breadth, top_vol,
            fut_sp, fut_nq,
        ) = await asyncio.gather(
            _fetch_naver_index(client, "KOSPI",  "코스피"),
            _fetch_naver_index(client, "KOSDAQ", "코스닥"),
            _fetch_yahoo(client, "%5EIXIC",  "나스닥"),
            _fetch_yahoo(client, "%5EGSPC",  "S&P500"),
            _fetch_yahoo(client, "%5EVIX",   "VIX"),
            _fetch_yahoo(client, "GC%3DF",   "금"),
            _fetch_yahoo(client, "CL%3DF",   "WTI"),
            _fetch_yahoo(client, "KRW%3DX",  "달러/원"),
            _fetch_yahoo(client, "JPYKRW%3DX", "엔/원"),
            _fetch_market_breadth(client),
            _fetch_top_volume(client),
            _fetch_yahoo(client, "ES%3DF",   "S&P500 선물"),
            _fetch_yahoo(client, "NQ%3DF",   "나스닥 선물"),
            return_exceptions=False,
        )

    # 달러/원은 역수로 표시됨 (Yahoo: USD per KRW → KRW per USD)
    if usd_krw["value"] and usd_krw["value"] < 1:
        rate = round(1 / usd_krw["value"], 2)
        prev_rate = round(1 / (usd_krw["value"] - usd_krw["change"]), 2) if usd_krw["change"] else rate
        usd_krw["value"] = rate
        usd_krw["change"] = round(rate - prev_rate, 2)
        usd_krw["change_pct"] = round((rate - prev_rate) / prev_rate * 100, 2) if prev_rate else 0

    result = {
        "indices": [kospi, kosdaq, nasdaq, sp500],
        "vix": vix,
        "forex": [usd_krw, jpy_krw],
        "commodities": [gold, wti],
        "futures": [fut_sp, fut_nq],
        "market_breadth": breadth,
        "top_volume": top_vol,
    }
    return _cached("overview", result)
