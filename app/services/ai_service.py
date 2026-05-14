import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# ── 분석 결과 캐시 ────────────────────────────────────────────────────────────
# 영속 캐시(파일)에서 먼저 조회하고, 없으면 Groq 호출 후 저장합니다.
from app.services import analysis_cache as _disk

_analysis_cache: dict[str, dict] = {}   # 하위 호환용 (영속 캐시가 우선)
_earnings_cache: dict[str, dict] = {}


def _cache_key(disclosure: dict) -> str:
    """공시의 고유 캐시 키 (rcept_no 우선, 없으면 corp+report 조합)"""
    rcept = disclosure.get("rcept_no", "")
    if rcept:
        return rcept
    return f"{disclosure.get('corp_name','')}|{disclosure.get('report_nm','')}"


def _is_rate_limit(exc: Exception) -> bool:
    return "429" in str(exc) or "rate_limit" in str(exc).lower()


def _rate_limit_error(exc: Exception) -> str:
    """429 에러를 사람이 읽을 수 있는 메시지로 변환"""
    msg = str(exc)
    # "Please try again in 2m10.464s" 부분 추출
    import re
    m = re.search(r"try again in ([^.]+)", msg)
    wait = m.group(1) if m else "잠시 후"
    return f"일일 AI 분석 한도 초과 — {wait} 후 다시 시도하세요 (Groq 무료 플랜 10만 토큰/일)"

PROMPT_TEMPLATE = """당신은 대한민국 소형주 전문 애널리스트입니다.
아래 공시 정보를 분석하고, 반드시 JSON 형식으로만 응답하세요.

회사명: {corp_name}
시가총액: {market_cap_억}억원
공시 제목: {report_nm}

분석 기준:
- score 8~10: 수주/계약/실적발표/대표이사변경/감사의견 등 주가에 직접 영향
- score 5~7: 산업 트렌드, 간접 수혜 가능성
- score 0~4: 단순 정기보고서, 시장 전반 내용, 중요도 낮음

key_amount_billion 추출:
- 유상증자/전환사채/신주인수권부사채/자기주식취득/수주계약 등 공시 제목에 금액이 명시된 경우 억원 단위로 추출
- 예: "(300억원)" → 300, "3,000,000,000원" → 30, "30백만달러" → null (외화는 null)
- 금액이 없거나 알 수 없으면 null

말투 규칙: summary와 reason은 반드시 구어체 종결어미(-음, -함, -있음, -없음, -임)로 작성. 예) "~있다" → "~있음", "~했다" → "~했음", "~이다" → "~임", "~된다" → "~됨".

응답 형식 (JSON만, 다른 텍스트 없이):
{{"score": 0~10 사이 정수, "sentiment": "positive" 또는 "negative" 또는 "neutral", "summary": "핵심 내용 1~2줄 요약", "reason": "이 점수를 준 이유 한 줄", "key_amount_billion": 억원 단위 숫자 또는 null}}"""




def _parse_amount(amount_str: str) -> int | None:
    """DART 금액 문자열 → 정수 변환 (콤마/부호 처리)"""
    if not amount_str or not amount_str.strip() or amount_str.strip() == "-":
        return None
    try:
        return int(amount_str.replace(",", "").strip())
    except ValueError:
        return None


def _calc_weather(curr: int | None, prev: int | None) -> tuple[str, float | None]:
    """전년동기 대비 영업이익 증감률 계산 및 맑음/흐림 판정"""
    if curr is None or prev is None:
        return "neutral", None
    if prev == 0:
        return ("sunny" if curr > 0 else "cloudy"), None

    change_pct = round((curr - prev) / abs(prev) * 100, 1)

    if prev < 0 and curr > 0:
        weather = "sunny"    # 흑자전환
    elif prev > 0 and curr < 0:
        weather = "cloudy"   # 적자전환
    elif prev < 0 and curr < 0:
        # 둘 다 적자 — 손실 폭 변화 기준으로 판정
        # curr < prev 이면 손실 확대(cloudy), curr > prev 이면 손실 축소(neutral)
        # 여전히 적자이므로 sunny는 쓰지 않음
        if change_pct >= 10:
            weather = "neutral"  # 적자 폭 감소 (하지만 여전히 적자)
        elif change_pct <= -10:
            weather = "cloudy"   # 적자 폭 확대
        else:
            weather = "neutral"
    elif change_pct >= 10:
        weather = "sunny"
    elif change_pct <= -10:
        weather = "cloudy"
    else:
        weather = "neutral"

    return weather, change_pct


def _fmt_profit(val: int | None) -> str:
    if val is None:
        return "데이터 없음"
    sign = "▼" if val < 0 else ""
    suffix = " (적자)" if val < 0 else ""
    abs_val = abs(val)
    if abs_val >= 100_000_000:           # 1억 이상 → 억원
        bil = round(abs_val / 100_000_000, 1)
        return f"{sign}{bil:g}억원{suffix}"
    if abs_val >= 10_000:                # 1만 이상 → 만원
        man = abs_val // 10_000
        return f"{sign}{man:,}만원{suffix}"
    return f"{sign}{abs_val:,}원{suffix}"


async def analyze_earnings_disclosure(disclosure: dict, profit_data: dict) -> dict:
    """영업실적 공시 — 전년동기 비교 + 맑음/흐림 판정 (코드 계산, AI 호출 없음)"""
    key = f"earnings:{_cache_key(disclosure)}"
    cached = _disk.get(key) or _earnings_cache.get(key)
    if cached:
        return {**disclosure, "ai": cached}

    has_profit_data = bool(profit_data)
    curr_val = _parse_amount(profit_data.get("current", "")) if has_profit_data else None
    prev_val = _parse_amount(profit_data.get("previous", "")) if has_profit_data else None
    weather, change_pct = _calc_weather(curr_val, prev_val)

    # 컨센서스 어닝쇼크 판정 (Naver Finance)
    shock_data: dict = {}
    stock_code = disclosure.get("stock_code", "")
    if stock_code and curr_val is not None:
        try:
            from app.services.comparison_service import fetch_naver_consensus, detect_earnings_shock
            consensus = await fetch_naver_consensus(stock_code)
            if consensus:
                curr_억 = curr_val / 1e8
                shock_data = detect_earnings_shock(curr_억, consensus["operating_profit_억"])
                shock_data["consensus_year"] = consensus["year"]
                shock_data["consensus_억"] = consensus["operating_profit_억"]
        except Exception:
            pass

    sentiment = "positive" if weather == "sunny" else "negative" if weather == "cloudy" else "neutral"
    result_ai = {
        "score": -1,
        "sentiment": sentiment,
        "summary": "",
        "reason": "",
        "weather": weather,
        "change_pct": change_pct,
        "curr_profit": curr_val,
        "prev_profit": prev_val,
        "shock_verdict": shock_data.get("verdict"),
        "shock_verdict_en": shock_data.get("verdict_en"),
        "shock_diff_pct": shock_data.get("diff_pct"),
        "shock_comment": shock_data.get("comment"),
        "consensus_억": shock_data.get("consensus_억"),
        "consensus_year": shock_data.get("consensus_year"),
    }

    _earnings_cache[key] = result_ai
    _disk.put(key, result_ai)
    return {**disclosure, "ai": result_ai}


async def analyze_disclosure(disclosure: dict) -> dict:
    """공시 1건 AI 분석 (key_amount_billion → 시총 대비 비율 코멘트 자동 생성)"""
    key = _cache_key(disclosure)
    # 영속 캐시 먼저 확인 (파일 기반, 서버 재시작 후에도 유지)
    cached = _disk.get(key) or _analysis_cache.get(key)
    if cached:
        return {**disclosure, "ai": cached}

    prompt = PROMPT_TEMPLATE.format(
        corp_name=disclosure.get("corp_name", ""),
        market_cap_억=disclosure.get("market_cap_억", "알 수 없음"),
        report_nm=disclosure.get("report_nm", ""),
    )

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        result = json.loads(response.choices[0].message.content)
    except Exception as e:
        err_msg = _rate_limit_error(e) if _is_rate_limit(e) else str(e)
        return {**disclosure, "ai": {"score": -1, "error": err_msg}}

    # 시총 대비 공시 금액 비교 코멘트 자동 삽입
    amount = result.get("key_amount_billion")
    market_cap = disclosure.get("market_cap_억")
    if amount and market_cap:
        from app.services.comparison_service import build_market_cap_comment
        cmp = build_market_cap_comment(float(amount), float(market_cap))
        result["market_cap_comment"] = cmp["comment"]
        result["market_cap_ratio_pct"] = cmp["ratio_pct"]
        result["market_cap_risk"] = cmp["risk_level"]
    else:
        result.setdefault("market_cap_comment", None)
        result.setdefault("market_cap_ratio_pct", None)
        result.setdefault("market_cap_risk", None)

    _analysis_cache[key] = result
    _disk.put(key, result)          # 파일에도 저장
    return {**disclosure, "ai": result}
