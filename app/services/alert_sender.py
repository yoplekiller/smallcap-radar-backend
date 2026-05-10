"""알림 발송 모듈 (Slack Incoming Webhook).

환경 변수:
  SLACK_WEBHOOK_URL  Slack Incoming Webhook URL
"""
import os
import httpx
from dotenv import load_dotenv

from app.services.alert_engine import AlertResult

load_dotenv()

_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL", "")

_SEVERITY_EMOJI = {
    "danger":      "🚨",
    "warning":     "⚠️",
    "opportunity": "💡",
}

_CONDITION_ICONS = {
    "market_cap_ratio":  "📊",
    "discount_rate":     "💸",
    "repeated_issuance": "🔁",
    "keyword_in_doc":    "🔍",
    "consensus_beat":    "📈",
}


def _build_slack_payload(alert: AlertResult) -> dict:
    emoji = _SEVERITY_EMOJI.get(alert.severity, "🔔")

    # 조건 목록 텍스트
    cond_lines = []
    for i, det in enumerate(alert.conditions_detail):
        icon = _CONDITION_ICONS.get(det.condition_type, "•")
        prefix = "┗" if i == len(alert.conditions_detail) - 1 else "┣"
        cond_lines.append(f"  {prefix} {icon} {det.label}")

    conditions_text = "\n".join(cond_lines) if cond_lines else "  (조건 상세 없음)"

    date_str = alert.rcept_dt
    if len(date_str) == 8:
        date_str = f"{date_str[:4]}.{date_str[4:6]}.{date_str[6:]}"

    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} {alert.title}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*회사*\n{alert.corp_name}"},
                {"type": "mrkdwn", "text": f"*종목코드*\n{alert.stock_code or '-'}"},
                {"type": "mrkdwn", "text": f"*공시일*\n{date_str}"},
                {"type": "mrkdwn", "text": f"*공시명*\n{alert.report_nm}"},
            ],
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*⚡ 트리거 조건:*\n{conditions_text}",
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*💡 판단:* {alert.comment}",
            },
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "공시 원문 보기"},
                    "url": alert.dart_url,
                    "style": "primary" if alert.severity == "opportunity" else "danger",
                }
            ],
        },
        {"type": "divider"},
    ]

    return {"blocks": blocks}


async def send_slack_alert(alert: AlertResult) -> bool:
    """Slack으로 알림을 발송합니다. 성공 여부 반환."""
    if not _WEBHOOK_URL:
        return False  # SLACK_WEBHOOK_URL 미설정

    payload = _build_slack_payload(alert)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(_WEBHOOK_URL, json=payload)
            return resp.status_code == 200
    except Exception:
        return False


async def send_slack_alerts_batch(alerts: list[AlertResult]) -> dict[str, bool]:
    """여러 알림을 순서대로 발송. {rcept_no+rule_id: success} 반환."""
    results = {}
    for alert in alerts:
        key = f"{alert.rcept_no}:{alert.rule_id}"
        results[key] = await send_slack_alert(alert)
    return results


async def send_web_push_alerts_batch(alerts: list[AlertResult]) -> None:
    """세력 포착 알림을 Web Push로도 발송."""
    from app.services.push_service import send_web_push

    for alert in alerts:
        emoji = _SEVERITY_EMOJI.get(alert.severity, "🔔")
        await send_web_push(
            title=f"{emoji} {alert.title}",
            body=f"{alert.corp_name} — {alert.comment}",
            url="/",
        )
