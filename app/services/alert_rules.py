"""알림 규칙 정의 모듈.

각 AlertRule은 사전 필터(keywords) + 조건 목록(conditions)으로 구성됩니다.
조건은 모두 AND로 연결됩니다(모든 조건 충족 시 알림 발송).
"""
from dataclasses import dataclass, field
from typing import Any, Literal

ConditionType = Literal[
    "market_cap_ratio",   # 공시 금액이 시총의 N% 이상
    "discount_rate",      # 전환가격이 현재가 대비 N% 이상 할인
    "repeated_issuance",  # 동일 기업이 N일 내 M회 이상 동일 유형 발행
    "keyword_in_doc",     # 공시 원문에 특정 키워드 포함
    "consensus_beat",     # 실적이 컨센서스 대비 N% 이상 상회
]

Severity = Literal["danger", "warning", "opportunity"]


@dataclass
class Condition:
    type: ConditionType
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class AlertRule:
    rule_id: str
    title: str          # 알림 타이틀 전체 (예: "[세력 포착: 위험] 대규모 할인 전환사채")
    name: str           # 짧은 규칙명
    severity: Severity
    keywords: list[str] # report_nm 사전 필터 (하나라도 포함되면 통과)
    conditions: list[Condition]
    comment_template: str  # 판단 이유 서술 (키: {market_cap_pct}, {discount_pct}, ...)


# ──────────────────────────────────────────────
# 내장 규칙 목록
# ──────────────────────────────────────────────

RULES: list[AlertRule] = [
    # ── 위험 시그널 ─────────────────────────────
    AlertRule(
        rule_id="cb_large_discount",
        title="[세력 포착: 위험] 대규모 할인 전환사채",
        name="대규모 할인 전환사채",
        severity="danger",
        keywords=["전환사채"],
        conditions=[
            Condition("market_cap_ratio", {"min_pct": 10}),
            Condition("discount_rate",    {"min_pct": 30}),
        ],
        comment_template=(
            "시총 {market_cap_pct:.1f}% 규모의 전환사채 발행 + "
            "현재가({stock_price:,}원) 대비 {discount_pct:.1f}% 할인 발행 → "
            "기존 주주가치 희석 및 메자닌 세력 개입 의심"
        ),
    ),
    AlertRule(
        rule_id="bw_large_discount",
        title="[세력 포착: 위험] 대규모 할인 신주인수권부사채",
        name="대규모 할인 BW",
        severity="danger",
        keywords=["신주인수권부사채", "BW"],
        conditions=[
            Condition("market_cap_ratio", {"min_pct": 10}),
            Condition("discount_rate",    {"min_pct": 25}),
        ],
        comment_template=(
            "시총 {market_cap_pct:.1f}% 규모의 BW 발행 + "
            "현재가({stock_price:,}원) 대비 {discount_pct:.1f}% 할인 → "
            "주가 하방 압력 및 세력 매집 구간 형성 우려"
        ),
    ),
    AlertRule(
        rule_id="rights_offering_massive",
        title="[세력 포착: 위험] 초대형 유상증자",
        name="초대형 유상증자",
        severity="danger",
        keywords=["유상증자"],
        conditions=[
            Condition("market_cap_ratio", {"min_pct": 30}),
        ],
        comment_template=(
            "시총 {market_cap_pct:.1f}% 규모의 대형 유상증자 → "
            "주가 희석 압력 극대화, 단기 낙폭 리스크"
        ),
    ),
    AlertRule(
        rule_id="repeated_cb",
        title="[세력 포착: 위험] 반복 전환사채 발행",
        name="반복 전환사채 발행",
        severity="danger",
        keywords=["전환사채"],
        conditions=[
            Condition("repeated_issuance", {"within_days": 180, "min_count": 2}),
        ],
        comment_template=(
            "최근 6개월 내 {count}회 전환사채 발행 → "
            "자금 조달 반복으로 메자닌 세력 지속 개입 의심"
        ),
    ),
    AlertRule(
        rule_id="repeated_bw",
        title="[세력 포착: 위험] 반복 신주인수권부사채 발행",
        name="반복 BW 발행",
        severity="danger",
        keywords=["신주인수권부사채"],
        conditions=[
            Condition("repeated_issuance", {"within_days": 180, "min_count": 2}),
        ],
        comment_template=(
            "최근 6개월 내 {count}회 BW 발행 → "
            "반복적 메자닌 조달로 세력 지속 개입 의심"
        ),
    ),
    AlertRule(
        rule_id="bad_audit",
        title="[세력 포착: 위험] 부정적 감사의견",
        name="부정적 감사의견",
        severity="danger",
        keywords=["감사보고서", "감사의견", "내부회계"],
        conditions=[
            Condition("keyword_in_doc", {"keywords": ["의견거절", "부적정", "한정의견", "한정"]}),
        ],
        comment_template=(
            "감사의견 이상 감지({found_keywords}) → "
            "상장폐지·거래정지 리스크, 즉시 확인 필요"
        ),
    ),
    AlertRule(
        rule_id="major_shareholder_dump",
        title="[세력 포착: 위험] 대주주 대규모 매도",
        name="대주주 대규모 매도",
        severity="danger",
        keywords=["주식등의대량보유상황보고", "대량보유"],
        conditions=[
            Condition("keyword_in_doc", {"keywords": ["처분", "매도"]}),
            Condition("market_cap_ratio", {"min_pct": 5}),
        ],
        comment_template=(
            "대주주 보유 지분 시총 {market_cap_pct:.1f}% 규모 처분 → "
            "내부자 대량 매도, 주가 하락 선행지표"
        ),
    ),
    AlertRule(
        rule_id="treasury_disposal",
        title="[세력 포착: 위험] 자기주식 대규모 처분",
        name="자기주식 처분",
        severity="danger",
        keywords=["자기주식처분", "자사주처분", "자기주식 처분결정"],
        conditions=[
            Condition("market_cap_ratio", {"min_pct": 5}),
        ],
        comment_template=(
            "시총 {market_cap_pct:.1f}% 규모 자사주 처분 → "
            "주가 부양 후 고점 매도 패턴 의심, 단기 하락 압력"
        ),
    ),

    # ── 기회 시그널 ─────────────────────────────
    AlertRule(
        rule_id="treasury_buyback",
        title="[세력 포착: 기회] 대규모 자사주 매입",
        name="대규모 자사주 매입",
        severity="opportunity",
        keywords=["자기주식취득", "자사주취득"],
        conditions=[
            Condition("market_cap_ratio", {"min_pct": 5}),
        ],
        comment_template=(
            "시총 {market_cap_pct:.1f}% 규모의 자사주 매입 → "
            "주가 지지력 확보, 저평가 신호로 해석 가능"
        ),
    ),
    AlertRule(
        rule_id="earnings_beat",
        title="[세력 포착: 기회] 어닝서프라이즈",
        name="컨센서스 대폭 상회",
        severity="opportunity",
        keywords=["실적", "영업이익"],
        conditions=[
            Condition("consensus_beat", {"min_beat_pct": 20}),
        ],
        comment_template=(
            "컨센서스 대비 {beat_pct:.1f}% 상회 → "
            "어닝서프라이즈, 기관 매집 유입 가능성"
        ),
    ),
]

# rule_id → AlertRule 빠른 조회용
RULES_BY_ID: dict[str, AlertRule] = {r.rule_id: r for r in RULES}
