import httpx
import asyncio
import time

SMALL_CAP_THRESHOLD = 300_000_000_000  # 3000억
PRICE_CACHE_TTL = 60  # 60초마다 갱신

_stock_cache: dict[str, tuple[float, dict | None]] = {}  # ticker -> (fetched_at, info)

NAVER_API = "https://m.stock.naver.com/api/stock/{ticker}/integration"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


async def filter_small_cap_disclosures(disclosures: list[dict]) -> list[dict]:
    """공시 목록에서 소형주만 필터링 + 가격 정보 첨부"""
    valid = [
        (item, item["stock_code"].strip())
        for item in disclosures
        if item.get("stock_code", "").strip()
    ]
    if not valid:
        return []

    unique_tickers = list({ticker for _, ticker in valid})
    info_map = await _fetch_stock_infos(unique_tickers)

    result = []
    for item, ticker in valid:
        info = info_map.get(ticker)
        if info and info.get("market_cap") is not None:
            cap = info["market_cap"]
            if cap < SMALL_CAP_THRESHOLD:
                item["market_cap"] = cap
                item["market_cap_억"] = round(cap / 100_000_000)
                if info.get("price"):
                    item["price"] = info["price"]
                    item["change_rate"] = info.get("change_rate")
                    item["change_amount"] = info.get("change_amount")
                result.append(item)

    return result


async def fetch_stock_price(ticker: str) -> dict | None:
    """단일 종목 현재가/등락률/시총 조회"""
    info_map = await _fetch_stock_infos([ticker])
    return info_map.get(ticker)


async def _fetch_stock_infos(tickers: list[str]) -> dict[str, dict | None]:
    """단일 httpx 클라이언트로 병렬 주식 정보 조회 (TTL 60초 캐싱)"""
    now = time.time()
    stale = [t for t in tickers if t not in _stock_cache or now - _stock_cache[t][0] > PRICE_CACHE_TTL]

    if stale:
        semaphore = asyncio.Semaphore(20)

        async def fetch_one(client: httpx.AsyncClient, ticker: str) -> tuple[str, dict | None]:
            async with semaphore:
                try:
                    r = await client.get(
                        NAVER_API.format(ticker=ticker),
                        headers=HEADERS,
                        timeout=3.0,
                    )
                    r.raise_for_status()
                    data = r.json()
                    return ticker, _parse_stock_info(data)
                except Exception:
                    return ticker, None

        limits = httpx.Limits(max_connections=30, max_keepalive_connections=20)
        async with httpx.AsyncClient(limits=limits) as client:
            results = await asyncio.gather(*[fetch_one(client, t) for t in stale])

        for ticker, info in results:
            if info is not None:
                _stock_cache[ticker] = (now, info)

    return {t: _stock_cache[t][1] if t in _stock_cache else None for t in tickers}


def _parse_stock_info(data: dict) -> dict | None:
    try:
        infos = data.get("totalInfos", [])
        deal_trends = data.get("dealTrendInfos", [])

        # 시총
        raw_cap = next((x["value"] for x in infos if x.get("code") == "marketValue"), None)
        market_cap = _parse_market_value(raw_cap)

        price = None
        change_rate = None
        change_amount = None

        if deal_trends:
            latest = deal_trends[0]

            price_raw = latest.get("closePrice", "")
            price = int(price_raw.replace(",", "")) if price_raw else None

            change_raw = latest.get("compareToPreviousClosePrice", "")
            change_amount = int(change_raw.replace(",", "")) if change_raw else None

            if price and change_amount is not None:
                prev_price = price - change_amount
                if prev_price > 0:
                    change_rate = round(change_amount / prev_price * 100, 2)

        # dealTrendInfos 없으면 totalInfos의 lastClosePrice로 폴백
        if price is None:
            raw_price = next((x["value"] for x in infos if x.get("code") == "lastClosePrice"), None)
            if raw_price:
                price = int(raw_price.replace(",", ""))

        return {
            "market_cap": market_cap,
            "price": price,
            "change_rate": change_rate,
            "change_amount": change_amount,
        }
    except Exception:
        return None


def _parse_market_value(value_str: str | None) -> int | None:
    if not value_str:
        return None

    value_str = value_str.replace(",", "").replace(" ", "")
    total = 0

    if "조" in value_str:
        parts = value_str.split("조")
        total += int(parts[0]) * 1_000_000_000_000
        value_str = parts[1]

    if "억" in value_str:
        total += int(value_str.split("억")[0]) * 100_000_000

    return total if total > 0 else None
