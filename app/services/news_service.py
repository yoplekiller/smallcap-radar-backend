import httpx
import re
import html

NAVER_NEWS_URL = "https://finance.naver.com/item/news_news.naver"
NAVER_NEWS_BASE = "https://finance.naver.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.naver.com",
}


async def fetch_stock_news(stock_code: str, limit: int = 5) -> list[dict]:
    """Naver Finance에서 종목 관련 뉴스 수집"""
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(
                NAVER_NEWS_URL,
                params={"code": stock_code, "page": 1},
                headers=HEADERS,
            )
            r.raise_for_status()
            content = r.content.decode("euc-kr", errors="replace")

        return _parse_news(content, limit)
    except Exception:
        return []


def _parse_news(content: str, limit: int) -> list[dict]:
    titles = re.findall(
        r'<td class="title">\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        content,
        re.DOTALL,
    )
    dates = re.findall(r'class="date"[^>]*>\s*(.*?)\s*<', content)
    presses = re.findall(r'class="info"[^>]*>\s*(.*?)\s*<', content)

    result = []
    for i, (url, title) in enumerate(titles[:limit]):
        clean_title = re.sub(r"<[^>]+>", "", title).strip()
        if not clean_title:
            continue
        result.append({
            "title": html.unescape(clean_title),
            "url": NAVER_NEWS_BASE + url.split("&sm=")[0] if url.startswith("/") else url.split("&sm=")[0],
            "date": dates[i].strip() if i < len(dates) else "",
            "press": presses[i].strip() if i < len(presses) else "",
        })

    return result
