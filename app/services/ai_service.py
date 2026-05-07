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
