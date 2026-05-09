import os
import json
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

client = Groq(api_key=os.getenv("GROQ_API_KEY"))

PROMPT_TEMPLATE = """당신은 대한민국 소형주 전문 애널리스트입니다.
아래 공시 정보를 분석하고, 반드시 JSON 형식으로만 응답하세요.

회사명: {corp_name}
시가총액: {market_cap_억}억원
공시 제목: {report_nm}

분석 기준:
- score 8~10: 수주/계약/실적발표/대표이사변경/감사의견 등 주가에 직접 영향
- score 5~7: 산업 트렌드, 간접 수혜 가능성
- score 0~4: 단순 정기보고서, 시장 전반 내용, 중요도 낮음

응답 형식 (JSON만, 다른 텍스트 없이):
{{"score": 0~10 사이 정수, "sentiment": "positive" 또는 "negative" 또는 "neutral", "summary": "핵심 내용 1~2줄 요약", "reason": "이 점수를 준 이유 한 줄"}}"""


NEWS_PROMPT = """당신은 주식 뉴스 분석 전문가입니다.
아래는 {corp_name}의 최근 뉴스 헤드라인입니다. 분석 후 반드시 JSON 형식으로만 응답하세요.

뉴스 목록:
{titles}

응답 형식 (JSON만, 다른 텍스트 없이):
{{"sentiment": "positive" 또는 "negative" 또는 "neutral", "summary": "최근 뉴스 동향 1~2줄 요약", "keywords": ["핵심 키워드 최대 3개"]}}"""


async def analyze_news(titles: list[str], corp_name: str) -> dict:
    """뉴스 헤드라인 목록 감성 분석"""
    if not titles:
        return {"sentiment": "neutral", "summary": "분석할 뉴스가 없습니다.", "keywords": []}

    titles_text = "\n".join(f"- {t}" for t in titles)
    prompt = NEWS_PROMPT.format(corp_name=corp_name or "해당 기업", titles=titles_text)

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        return {"sentiment": "neutral", "summary": "", "keywords": [], "error": str(e)}


EARNINGS_PROMPT = """당신은 대한민국 소형주 전문 애널리스트입니다.
아래 기업의 영업실적 공시를 분석하고, 반드시 JSON 형식으로만 응답하세요.

회사명: {corp_name}
시가총액: {market_cap_억}억원
공시 제목: {report_nm}
영업이익 전년동기: {prev_profit}
영업이익 당기: {curr_profit}
전년동기 대비 증감: {change_pct}

분석 요청:
- 이 실적이 소형주 투자자 관점에서 어떤 의미인지 판단
- 성장세/수익성/시장 기대치 충족 여부를 간결하게 평가

응답 형식 (JSON만, 다른 텍스트 없이):
{{"summary": "핵심 실적 요약 1~2줄", "assessment": "투자자 관점 영향 전망 한 줄"}}"""


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
        weather = "sunny"   # 흑자전환
    elif prev > 0 and curr < 0:
        weather = "cloudy"  # 적자전환
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
    bil = val // 100_000_000
    if abs(bil) >= 10:
        return f"{bil:,}억원"
    mil = val // 1_000_000
    return f"{mil:,}백만원"


async def analyze_earnings_disclosure(disclosure: dict, profit_data: dict) -> dict:
    """영업실적 공시 전용 AI 분석 (전년동기 비교 + 맑음/흐림)"""
    curr_val = _parse_amount(profit_data.get("current", ""))
    prev_val = _parse_amount(profit_data.get("previous", ""))
    weather, change_pct = _calc_weather(curr_val, prev_val)

    change_str = (
        f"{change_pct:+.1f}%" if change_pct is not None
        else "전년동기 데이터 없음"
    )

    prompt = EARNINGS_PROMPT.format(
        corp_name=disclosure.get("corp_name", ""),
        market_cap_억=disclosure.get("market_cap_억", "알 수 없음"),
        report_nm=disclosure.get("report_nm", ""),
        prev_profit=_fmt_profit(prev_val),
        curr_profit=_fmt_profit(curr_val),
        change_pct=change_str,
    )

    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        ai_result = json.loads(response.choices[0].message.content)
    except Exception as e:
        ai_result = {"summary": "", "assessment": "", "error": str(e)}

    sentiment = "positive" if weather == "sunny" else "negative" if weather == "cloudy" else "neutral"
    result_ai = {
        "score": -1,
        "sentiment": sentiment,
        "summary": ai_result.get("summary", ""),
        "reason": ai_result.get("assessment", ""),
        "weather": weather,
        "change_pct": change_pct,
        "curr_profit": curr_val,
        "prev_profit": prev_val,
    }
    if "error" in ai_result:
        result_ai["error"] = ai_result["error"]

    return {**disclosure, "ai": result_ai}


async def analyze_disclosure(disclosure: dict) -> dict:
    """공시 1건 AI 분석"""
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
        return {**disclosure, "ai": result}
    except Exception as e:
        return {**disclosure, "ai": {"score": -1, "error": str(e)}}
