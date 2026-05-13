"""알림 관련 API 라우터 + 스케줄러 Job 함수.

엔드포인트:
  GET  /alerts/rules              — 등록된 규칙 목록
  GET  /alerts/history            — 최근 알림 이력 (limit 파라미터)
  POST /alerts/test/{rcept_no}    — 특정 공시에 대해 수동으로 엔진 실행
  POST /alerts/run                — 즉시 알림 점검 실행 (수동 트리거)
"""
import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException

from app.services.alert_engine import AlertResult, evaluate_disclosure
from app.services.alert_rules import RULES
from app.services.alert_sender import send_slack_alert, send_push_alerts_batch
from app.services.alert_store import (
    get_history,
    get_last_checked_at,
    is_already_sent,
    record_alert,
    set_last_checked_at,
)

router = APIRouter(prefix="/alerts", tags=["알림"])

_CHECK_LOCK = asyncio.Lock()   # 동시 실행 방지


# ──────────────────────────────────────────────────────────────────────────────
# 규칙 목록
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/rules")
async def list_rules():
    """등록된 알림 규칙 목록 반환"""
    return [
        {
            "rule_id":   r.rule_id,
            "title":     r.title,
            "name":      r.name,
            "severity":  r.severity,
            "keywords":  r.keywords,
            "conditions": [{"type": c.type, "params": c.params} for c in r.conditions],
        }
        for r in RULES
    ]


# ──────────────────────────────────────────────────────────────────────────────
# 알림 이력
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/history")
async def alert_history(limit: int = 50):
    """최근 알림 이력 조회"""
    return {"data": get_history(limit), "count": len(get_history(limit))}


# ──────────────────────────────────────────────────────────────────────────────
# 특정 공시 수동 테스트
# ──────────────────────────────────────────────────────────────────────────────

@router.post("/test/{rcept_no}")
async def test_alert(rcept_no: str, disclosure: dict[str, Any]):
    """공시 데이터를 직접 받아 알림 엔진 실행 (실제 알림 미발송, 평가 결과만 반환)"""
    try:
        alerts = await evaluate_disclosure({**disclosure, "rcept_no": rcept_no})
        return {
            "rcept_no": rcept_no,
            "alerts_triggered": len(alerts),
            "results": [
                {
                    "rule_id": a.rule_id,
                    "title":   a.title,
                    "severity": a.severity,
                    "comment": a.comment,
                    "conditions_detail": [
                        {
                            "type":      d.condition_type,
                            "label":     d.label,
                            "passed":    d.passed,
                            "value":     d.value,
                            "threshold": d.threshold,
                        }
                        for d in a.conditions_detail
                    ],
                }
                for a in alerts
            ],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ──────────────────────────────────────────────────────────────────────────────
# 알림 점검 실행 (스케줄러 Job + 수동 트리거 공유)
# ──────────────────────────────────────────────────────────────────────────────

async def run_alert_check(days: int = 1) -> dict:
    """최근 N일 공시 전체를 알림 엔진으로 점검하고 Slack 발송.

    스케줄러와 /alerts/run 엔드포인트가 함께 사용합니다.
    """
    if _CHECK_LOCK.locked():
        return {"status": "already_running"}

    async with _CHECK_LOCK:
        from app.services.dart_service import fetch_recent_disclosures

        disclosures = await fetch_recent_disclosures(days)
        sent_count  = 0
        skip_count  = 0
        results: list[dict] = []
        new_alerts: list = []

        for disc in disclosures:
            alerts = await evaluate_disclosure(disc)
            for alert in alerts:
                key_dup = is_already_sent(alert.rcept_no, alert.rule_id)
                if key_dup:
                    skip_count += 1
                    continue

                sent = await send_slack_alert(alert)
                new_alerts.append(alert)

                record_alert(
                    rcept_no=alert.rcept_no,
                    rule_id=alert.rule_id,
                    corp_name=alert.corp_name,
                    stock_code=alert.stock_code,
                    title=alert.title,
                    comment=alert.comment,
                    conditions_detail=[
                        {
                            "type":      d.condition_type,
                            "label":     d.label,
                            "passed":    d.passed,
                            "value":     d.value,
                            "threshold": d.threshold,
                        }
                        for d in alert.conditions_detail
                    ],
                    sent=sent,
                    market_cap_억=alert.market_cap_억,
                    stock_price=alert.stock_price,
                )
                sent_count += 1
                results.append({
                    "corp_name": alert.corp_name,
                    "title":     alert.title,
                    "sent":      sent,
                })

        if new_alerts:
            await send_push_alerts_batch(new_alerts)

        set_last_checked_at(datetime.now(timezone.utc))

        return {
            "status":       "ok",
            "checked":      len(disclosures),
            "sent":         sent_count,
            "skipped":      skip_count,
            "last_checked": datetime.now(timezone.utc).isoformat(),
            "results":      results,
        }


@router.post("/run")
async def manual_run(days: int = 1):
    """즉시 알림 점검 실행 (수동 트리거)"""
    try:
        result = await run_alert_check(days)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def alert_status():
    """마지막 점검 시각 + 미발송 여부 확인"""
    last = get_last_checked_at()
    history = get_history(5)
    return {
        "last_checked_at": last,
        "slack_enabled":   bool(__import__("os").getenv("SLACK_WEBHOOK_URL")),
        "recent_alerts":   history,
    }
