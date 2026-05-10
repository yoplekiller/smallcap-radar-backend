"""알림 엔진 — 개별 공시를 AlertRule 목록 대비 평가.

평가 흐름:
  1. report_nm 키워드 사전 필터 (빠른 탈락)
  2. 시장 데이터 조회 (Naver Finance, 조건에 필요 시)
  3. 공시 원문 AI 추출 (할인율·키워드 조건에 필요 시)
  4. 모든 조건 AND 평가
  5. 트리거된 경우 AlertResult 반환
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any

from groq import Groq
from dotenv import load_dotenv

from app.services.alert_rules import AlertRule, Condition, RULES
from app.services.market_cap_service import fetch_stock_price

load_dotenv()

_groq = Groq(api_key=os.getenv("GROQ_API_KEY"))


# ──────────────────────────────────────────────────────────────────────────────
# 결과 타입
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ConditionDetail:
    condition_type: str
    label: str           # 사람이 읽을 수 있는 설명
    passed: bool
    value: Any = None    # 실측값
    threshold: Any = None

@dataclass
class AlertResult:
    rule_id: str
    title: str           # "[세력 포착: 위험] 대규모 할인 전환사채"
    severity: str
    rcept_no: str
    corp_name: str
    report_nm: str
    rcept_dt: str
    stock_code: str
    comment: str         # 판단 이유
    conditions_detail: list[ConditionDetail] = field(default_factory=list)
    dart_url: str = ""
    market_cap_억: float | None = None
    stock_price: float | None = None

    def __post_init__(self):
        if self.rcept_no:
            self.dart_url = f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={self.rcept_no}"


# ──────────────────────────────────────────────────────────────────────────────
# 금액 추출 (report_nm 우선, AI 폴백)
# ──────────────────────────────────────────────────────────────────────────────

def _extract_amount_from_nm(report_nm: str) -> float | None:
    """공시 제목에서 금액(억원)을 추출합니다."""
    # 패턴: "150억원", "1,500,000,000원(150억)" 등
    patterns = [
        (r"(\d[\d,]+)억원?",           lambda m: float(m.group(1).replace(",", ""))),
        (r"(\d[\d,]+),000,000,000원?", lambda m: float(m.group(1).replace(",", "")) * 10),  # 십억 단위
        (r"(\d[\d,]+),000,000원?",     lambda m: float(m.group(1).replace(",", "")) / 10),  # 천만 단위
    ]
    for pattern, extractor in patterns:
        m = re.search(pattern, report_nm)
        if m:
            try:
                return extractor(m)
            except ValueError:
                continue
    return None


async def _extract_from_document(rcept_no: str, corp_name: str) -> dict:
    """공시 원문 AI 추출: 발행금액, 전환가격, 키워드."""
    try:
        from src.api.dart_provider import DartProvider
        provider = DartProvider()
        doc_text = await provider.get_document_text(rcept_no)
        # 최대 8000자 (Groq 컨텍스트 절약)
        doc_short = re.sub(r'<[^>]+>', ' ', doc_text)
        doc_short = re.sub(r'\s+', ' ', doc_short).strip()[:8000]
    except Exception:
        return {}

    prompt = f"""아래 공시 원문({corp_name})에서 정보를 추출하고 JSON으로만 응답하세요.
없는 항목은 null로 반환하세요.

원문:
{doc_short}

응답 형식:
{{
  "issue_amount_억": 발행금액(억원, 숫자),
  "conversion_price_원": 전환가격 또는 행사가격(원/주, 숫자),
  "audit_opinion_keywords": ["의견거절","부적정","한정의견" 중 원문에 등장하는 것들],
  "action_keywords": ["처분","매도","매입" 중 등장하는 것들]
}}"""

    try:
        resp = _groq.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        return json.loads(resp.choices[0].message.content or "{}")
    except Exception:
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# 조건 평가기
# ──────────────────────────────────────────────────────────────────────────────

async def _eval_market_cap_ratio(
    cond: Condition,
    amount_억: float | None,
    market_cap_억: float | None,
) -> ConditionDetail:
    min_pct: float = cond.params["min_pct"]
    if amount_억 is None or market_cap_억 is None or market_cap_억 == 0:
        return ConditionDetail("market_cap_ratio", "시총 대비 금액", False,
                               value=None, threshold=min_pct)
    ratio = round(amount_억 / market_cap_억 * 100, 1)
    return ConditionDetail(
        "market_cap_ratio",
        f"발행금액 {amount_억:,.0f}억원 → 시총의 {ratio:.1f}% (기준: {min_pct}% 이상)",
        ratio >= min_pct,
        value=ratio,
        threshold=min_pct,
    )


def _eval_discount_rate(
    cond: Condition,
    conversion_price: float | None,
    stock_price: float | None,
) -> ConditionDetail:
    min_pct: float = cond.params["min_pct"]
    if conversion_price is None or stock_price is None or stock_price == 0:
        return ConditionDetail("discount_rate", "전환가격 할인율", False,
                               value=None, threshold=min_pct)
    discount = round((stock_price - conversion_price) / stock_price * 100, 1)
    return ConditionDetail(
        "discount_rate",
        f"전환가격 {conversion_price:,.0f}원 / 현재가 {stock_price:,.0f}원 → {discount:.1f}% 할인 (기준: {min_pct}% 이상)",
        discount >= min_pct,
        value=discount,
        threshold=min_pct,
    )


async def _eval_repeated_issuance(
    cond: Condition,
    disclosure: dict,
) -> ConditionDetail:
    within_days: int = cond.params["within_days"]
    min_count: int   = cond.params["min_count"]
    corp_code = disclosure.get("corp_code", "")
    report_nm = disclosure.get("report_nm", "")

    if not corp_code:
        return ConditionDetail("repeated_issuance", "반복 발행", False)

    try:
        from src.api.dart_provider import DartProvider
        from datetime import date, timedelta
        provider = DartProvider()
        end = date.today()
        start = end - timedelta(days=within_days)
        items = await provider.get_all_disclosures(
            corp_code,
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
        )
        # 동일 유형 (전환사채/BW) 공시 횟수 집계
        kw = next((k for k in ["전환사채", "신주인수권부사채", "BW"] if k in report_nm), "")
        count = sum(1 for it in items if kw and kw in it.get("report_nm", ""))
        passed = count >= min_count
        return ConditionDetail(
            "repeated_issuance",
            f"{within_days}일 내 동종 공시 {count}회 (기준: {min_count}회 이상)",
            passed,
            value=count,
            threshold=min_count,
        )
    except Exception:
        return ConditionDetail("repeated_issuance", "반복 발행 (조회 실패)", False)


def _eval_keyword_in_doc(
    cond: Condition,
    doc_data: dict,
) -> ConditionDetail:
    keywords: list[str] = cond.params["keywords"]
    audit_kws = doc_data.get("audit_opinion_keywords") or []
    action_kws = doc_data.get("action_keywords") or []
    all_found = list({*audit_kws, *action_kws})
    matched = [k for k in keywords if k in all_found]
    return ConditionDetail(
        "keyword_in_doc",
        f"원문 키워드: {matched if matched else '없음'} (기준: {keywords} 중 하나 이상)",
        len(matched) > 0,
        value=matched,
        threshold=keywords,
    )


async def _eval_consensus_beat(
    cond: Condition,
    disclosure: dict,
) -> ConditionDetail:
    min_beat: float = cond.params["min_beat_pct"]
    stock_code = disclosure.get("stock_code", "")
    corp_code  = disclosure.get("corp_code", "")
    rcept_dt   = disclosure.get("rcept_dt", "")

    if not stock_code or not corp_code or not rcept_dt:
        return ConditionDetail("consensus_beat", "컨센서스 상회율", False)

    try:
        from app.services.dart_service import fetch_operating_profit
        from app.services.comparison_service import fetch_naver_consensus, detect_earnings_shock
        from app.services.ai_service import _parse_amount

        profit_data = await fetch_operating_profit(corp_code, rcept_dt)
        if not profit_data:
            return ConditionDetail("consensus_beat", "실적 데이터 없음", False)

        curr_val = _parse_amount(profit_data.get("current", ""))
        if curr_val is None:
            return ConditionDetail("consensus_beat", "영업이익 파싱 실패", False)

        consensus = await fetch_naver_consensus(stock_code)
        if not consensus:
            return ConditionDetail("consensus_beat", "컨센서스 데이터 없음", False)

        curr_억 = curr_val / 1e8
        shock = detect_earnings_shock(curr_억, consensus["operating_profit_억"])
        beat_pct = shock.get("diff_pct")
        if beat_pct is None:
            return ConditionDetail("consensus_beat", "비교 불가", False)

        passed = beat_pct >= min_beat
        return ConditionDetail(
            "consensus_beat",
            f"실적 {curr_억:,.0f}억 / 컨센서스 {consensus['operating_profit_억']:,.0f}억 → {beat_pct:+.1f}% (기준: +{min_beat}% 이상)",
            passed,
            value=beat_pct,
            threshold=min_beat,
        )
    except Exception:
        return ConditionDetail("consensus_beat", "컨센서스 비교 실패", False)


# ──────────────────────────────────────────────────────────────────────────────
# 공시 1건 전체 평가
# ──────────────────────────────────────────────────────────────────────────────

async def evaluate_disclosure(disclosure: dict, rules: list[AlertRule] | None = None) -> list[AlertResult]:
    """공시 1건에 대해 매칭 규칙을 찾아 AlertResult 목록을 반환합니다."""
    if rules is None:
        rules = RULES

    report_nm  = disclosure.get("report_nm", "")
    corp_name  = disclosure.get("corp_name", "")
    rcept_no   = disclosure.get("rcept_no", "")
    rcept_dt   = disclosure.get("rcept_dt", "")
    stock_code = disclosure.get("stock_code", "").strip()

    # ── 시장 데이터 (1회만 조회) ──────────────────
    stock_info: dict | None = None
    market_cap_억: float | None = None
    stock_price: float | None   = None

    if stock_code:
        stock_info = await fetch_stock_price(stock_code)
        if stock_info and stock_info.get("market_cap"):
            market_cap_억 = round(stock_info["market_cap"] / 1e8, 1)
        if stock_info and stock_info.get("price"):
            stock_price = float(stock_info["price"])

    results: list[AlertResult] = []

    # 조건별로 한 번만 필요한 원문 데이터를 지연 로드
    _doc_data: dict | None = None

    async def get_doc_data() -> dict:
        nonlocal _doc_data
        if _doc_data is None:
            _doc_data = await _extract_from_document(rcept_no, corp_name)
        return _doc_data

    for rule in rules:
        # ── 사전 필터: 키워드 ─────────────────────
        if not any(kw in report_nm for kw in rule.keywords):
            continue

        # ── 조건 평가 ─────────────────────────────
        details: list[ConditionDetail] = []
        needs_doc = any(c.type in ("discount_rate", "keyword_in_doc") for c in rule.conditions)
        doc_data = await get_doc_data() if needs_doc else {}

        # 발행금액 (report_nm 우선 → 문서 AI 폴백)
        amount_억 = _extract_amount_from_nm(report_nm)
        if amount_억 is None and doc_data:
            raw = doc_data.get("issue_amount_억")
            if raw is not None:
                try:
                    amount_억 = float(raw)
                except (TypeError, ValueError):
                    pass

        # 전환가격
        conversion_price = None
        if doc_data:
            raw_cp = doc_data.get("conversion_price_원")
            if raw_cp is not None:
                try:
                    conversion_price = float(str(raw_cp).replace(",", ""))
                except (TypeError, ValueError):
                    pass

        all_passed = True
        for cond in rule.conditions:
            if cond.type == "market_cap_ratio":
                det = await _eval_market_cap_ratio(cond, amount_억, market_cap_억)
            elif cond.type == "discount_rate":
                det = _eval_discount_rate(cond, conversion_price, stock_price)
            elif cond.type == "repeated_issuance":
                det = await _eval_repeated_issuance(cond, disclosure)
            elif cond.type == "keyword_in_doc":
                det = _eval_keyword_in_doc(cond, doc_data)
            elif cond.type == "consensus_beat":
                det = await _eval_consensus_beat(cond, disclosure)
            else:
                det = ConditionDetail(cond.type, f"미지원 조건({cond.type})", False)

            details.append(det)
            if not det.passed:
                all_passed = False

        if not all_passed:
            continue

        # ── 코멘트 생성 ───────────────────────────
        fmt_vars: dict[str, Any] = {
            "market_cap_pct": next((d.value for d in details if d.condition_type == "market_cap_ratio"), 0) or 0,
            "discount_pct":   next((d.value for d in details if d.condition_type == "discount_rate"), 0) or 0,
            "stock_price":    int(stock_price or 0),
            "count":          next((d.value for d in details if d.condition_type == "repeated_issuance"), 0) or 0,
            "found_keywords": next((d.value for d in details if d.condition_type == "keyword_in_doc"), []) or [],
            "beat_pct":       next((d.value for d in details if d.condition_type == "consensus_beat"), 0) or 0,
        }
        try:
            comment = rule.comment_template.format(**fmt_vars)
        except (KeyError, ValueError):
            comment = rule.name

        results.append(AlertResult(
            rule_id=rule.rule_id,
            title=rule.title,
            severity=rule.severity,
            rcept_no=rcept_no,
            corp_name=corp_name,
            report_nm=report_nm,
            rcept_dt=rcept_dt,
            stock_code=stock_code,
            comment=comment,
            conditions_detail=details,
            market_cap_억=market_cap_억,
            stock_price=stock_price,
        ))

    return results
