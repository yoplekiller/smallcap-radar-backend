import httpx
import asyncio
from datetime import date, timedelta

SMALL_CAP_THRESHOLD = 300_000_000_000  # 3000억

_ticker_cache: dict[str, int | None] = {}  # ticker → 시가총액 캐시
_semaphore = asyncio.Semaphore(10)  # 동시 요청 최대 10개

NAVER_API = "https://m.stock.naver.com/api/stock/{ticker}/integration"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


async def get_market_cap_naver(ticker: str) -> int | None:
    """Naver Finance에서 단일 종목 시가총액 조회 (캐싱 + 동시 요청 제한)"""
    if ticker in _ticker_cache:
        return _ticker_cache[ticker]

    url = NAVER_API.format(ticker=ticker)
    try:
        async with _semaphore:
            async with httpx.AsyncClient(timeout=8) as client:
                response = await client.get(url, headers=HEADERS)
                response.raise_for_status()
                data = response.json()

        total_infos = data.get("totalInfos", [])
        market_value_str = next(
            (item["value"] for item in total_infos if item.get("code") == "marketValue"),
            None,
        )
        result = _parse_market_value(market_value_str)
        _ticker_cache[ticker] = result
        return result
    except Exception:
        _ticker_cache[ticker] = None
        return None


def _parse_market_value(value_str: str) -> int | None:
    """'1조 2,345억' 또는 '2,345억' 문자열 → 원 단위 정수"""
    if not value_str:
        return None

    value_str = value_str.replace(",", "").replace(" ", "")
    total = 0

    if "조" in value_str:
        parts = value_str.split("조")
        total += int(parts[0]) * 1_000_000_000_000
        value_str = parts[1]

    if "억" in value_str:
        parts = value_str.split("억")
        total += int(parts[0]) * 100_000_000

    return total if total > 0 else None


async def filter_small_cap_disclosures(disclosures: list[dict]) -> list[dict]:
    """공시 목록에서 소형주만 필터링 (중복 ticker 제거 후 병렬 처리)"""
    valid = [(item, item.get("stock_code", "").strip()) for item in disclosures if item.get("stock_code", "").strip()]

    # 고유 ticker만 API 호출
    unique_tickers = list({ticker for _, ticker in valid})
    caps = await asyncio.gather(*[get_market_cap_naver(t) for t in unique_tickers])
    cap_map = dict(zip(unique_tickers, caps))

    result = []
    for item, ticker in valid:
        market_cap = cap_map.get(ticker)
        if market_cap is not None and market_cap < SMALL_CAP_THRESHOLD:
            item["market_cap"] = market_cap
            item["market_cap_억"] = round(market_cap / 100_000_000)
            result.append(item)

    return result
