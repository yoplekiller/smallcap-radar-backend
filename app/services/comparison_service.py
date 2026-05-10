import httpx
from typing import Optional

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
_NAVER_CONSENSUS_URL = "https://m.stock.naver.com/api/stock/{code}/consensus/annual"

# ──────────────────────────────────────────────────────────────────────────────
# 시가총액 대비 공시 금액 비교
# ──────────────────────────────────────────────────────────────────────────────

def build_market_cap_comment(amount_억: float, market_cap_억: float) -> dict:
    """공시 금액이 시가총액의 몇 %인지 계산하고 코멘트를 생성합니다.

    Args:
        amount_억:     공시 금액 (억원)
        market_cap_억: 현재 시가총액 (억원)

    Returns:
        {ratio_pct, scale, risk_level, comment}
    """
    if market_cap_억 <= 0:
        return {"ratio_pct": None, "scale": None, "risk_level": None, "comment": "시총 정보 없음"}

    ratio_pct = round(amount_억 / market_cap_억 * 100, 1)

    if ratio_pct >= 50:
        scale, risk_level = "초대형", "critical"
    elif ratio_pct >= 30:
        scale, risk_level = "대형", "high"
    elif ratio_pct >= 10:
        scale, risk_level = "중형", "medium"
    else:
        scale, risk_level = "소형", "low"

    comment = f"이번 공시 금액은 시가총액의 {ratio_pct:.1f}% 규모입니다 ({scale} 이벤트)"
    return {
        "ratio_pct": ratio_pct,
        "scale": scale,
        "risk_level": risk_level,
        "comment": comment,
        "amount_억": amount_억,
        "market_cap_억": market_cap_억,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Naver Finance 컨센서스 조회
# ──────────────────────────────────────────────────────────────────────────────

async def fetch_naver_consensus(stock_code: str) -> Optional[dict]:
    """Naver Finance 증권사 컨센서스 영업이익 조회.

    Returns:
        {year, operating_profit_억, revenue_억} 또는 None
    """
    url = _NAVER_CONSENSUS_URL.format(code=stock_code)
    try:
        async with httpx.AsyncClient(timeout=5, headers=_HEADERS) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
        return _parse_consensus(data)
    except Exception:
        return None


def _parse_consensus(data: dict) -> Optional[dict]:
    items = (
        data.get("consensusList")
        or data.get("yearList")
        or data.get("list")
        or []
    )
    if not items:
        return None

    latest = items[0]

    # 다양한 필드명 대응 (네이버 API 버전별 차이)
    op_raw = (
        latest.get("operatingProfit")
        or latest.get("operatingProfitMean")
        or latest.get("영업이익")
    )
    rev_raw = (
        latest.get("revenue")
        or latest.get("revenueMean")
        or latest.get("매출액")
    )

    if op_raw is None:
        return None

    op_val = float(op_raw)
    rev_val = float(rev_raw or 0)

    # 단위 추론: 값이 100억(1_000_000_000원) 이상이면 원 단위, 미만이면 백만원 단위
    if op_val >= 1_000_000_000:
        op_억 = round(op_val / 1e8, 1)      # 원 → 억원
        rev_억 = round(rev_val / 1e8, 1)
    else:
        op_억 = round(op_val / 100, 1)       # 백만원 → 억원
        rev_억 = round(rev_val / 100, 1)

    year = (
        latest.get("yearMonth")
        or latest.get("year")
        or latest.get("bsnsYear")
        or ""
    )
    # "202512" → "2025"
    if len(str(year)) == 6:
        year = str(year)[:4]

    return {
        "year": str(year),
        "operating_profit_억": op_억,
        "revenue_억": rev_억,
        "raw": latest,
    }


# ──────────────────────────────────────────────────────────────────────────────
# 어닝쇼크 판정
# ──────────────────────────────────────────────────────────────────────────────

def detect_earnings_shock(actual_억: float, consensus_억: float) -> dict:
    """실제 영업이익 vs 컨센서스 비교 → 어닝쇼크/서프라이즈 판정.

    Args:
        actual_억:    실제 영업이익 (억원)
        consensus_억: 컨센서스 영업이익 (억원)

    Returns:
        {verdict, verdict_en, diff_pct, comment}
    """
    if not consensus_억 or consensus_억 == 0:
        return {
            "verdict": "비교 불가",
            "verdict_en": "unavailable",
            "diff_pct": None,
            "comment": "컨센서스 데이터가 없어 비교할 수 없습니다.",
        }

    diff_pct = round((actual_억 - consensus_억) / abs(consensus_억) * 100, 1)

    if diff_pct <= -20:
        verdict, verdict_en = "어닝쇼크", "shock"
    elif diff_pct <= -10:
        verdict, verdict_en = "예상 하회", "miss"
    elif diff_pct >= 20:
        verdict, verdict_en = "어닝서프라이즈", "beat"
    elif diff_pct >= 10:
        verdict, verdict_en = "예상 상회", "beat_minor"
    else:
        verdict, verdict_en = "컨센서스 부합", "inline"

    sign = "+" if diff_pct >= 0 else ""
    comment = (
        f"영업이익 {actual_억:,.0f}억원 "
        f"(컨센서스 {consensus_억:,.0f}억원 대비 {sign}{diff_pct:.1f}%) "
        f"→ {verdict}"
    )

    return {
        "verdict": verdict,
        "verdict_en": verdict_en,
        "diff_pct": diff_pct,
        "actual_억": actual_억,
        "consensus_억": consensus_억,
        "comment": comment,
    }
