"""알림 이력 관리 (data/alert_history.json).

- 중복 발송 방지: (rcept_no, rule_id) 기준으로 이미 발송된 알림은 건너뜀
- 최대 500건 보관 (초과 시 오래된 것부터 삭제)
"""
import json
import os
from datetime import datetime, timezone
from typing import Any
import uuid

_STORE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "alert_history.json"
)
_MAX_RECORDS = 500


def _load() -> list[dict]:
    try:
        with open(_STORE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _save(records: list[dict]) -> None:
    os.makedirs(os.path.dirname(_STORE_PATH), exist_ok=True)
    with open(_STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)


def is_already_sent(rcept_no: str, rule_id: str) -> bool:
    """동일 공시 + 동일 규칙 알림이 이미 발송됐는지 확인"""
    records = _load()
    return any(
        r["rcept_no"] == rcept_no and r["rule_id"] == rule_id
        for r in records
    )


def record_alert(
    *,
    rcept_no: str,
    rule_id: str,
    corp_name: str,
    stock_code: str = "",
    title: str,
    comment: str,
    conditions_detail: list[dict[str, Any]],
    sent: bool,
    market_cap_억: float | None = None,
    stock_price: float | None = None,
) -> dict:
    """알림 이력 저장 후 저장된 레코드 반환"""
    record = {
        "id": str(uuid.uuid4()),
        "rcept_no": rcept_no,
        "rule_id": rule_id,
        "corp_name": corp_name,
        "stock_code": stock_code,
        "title": title,
        "comment": comment,
        "conditions_detail": conditions_detail,
        "sent": sent,
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "market_cap_억": market_cap_억,
        "stock_price": stock_price,
        "price_tracking": {},
    }
    records = _load()
    records.insert(0, record)
    _save(records[:_MAX_RECORDS])
    return record


def get_history(limit: int = 50) -> list[dict]:
    return _load()[:limit]


def get_last_checked_at() -> str | None:
    """마지막 알림 점검 시각 반환 (ISO 8601)"""
    try:
        meta_path = _STORE_PATH.replace("alert_history.json", "alert_meta.json")
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f).get("last_checked_at")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def set_last_checked_at(dt: datetime) -> None:
    meta_path = _STORE_PATH.replace("alert_history.json", "alert_meta.json")
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"last_checked_at": dt.isoformat()}, f)
