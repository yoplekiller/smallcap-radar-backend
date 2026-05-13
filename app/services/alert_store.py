"""알림 이력 관리.

DATABASE_URL 있으면 PostgreSQL, 없으면 파일 (로컬 개발용).
- 중복 발송 방지: (rcept_no, rule_id) 기준
- 최대 500건 (파일 모드만 해당, DB는 제한 없음)
"""
import json
import os
from datetime import datetime, timezone
from typing import Any
import uuid

from sqlalchemy import text

from app.db import USE_DB, engine

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
    if USE_DB:
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("""
                        SELECT 1 FROM alert_history
                        WHERE rcept_no = :r AND rule_id = :rid
                        LIMIT 1
                    """),
                    {"r": rcept_no, "rid": rule_id},
                ).fetchone()
                return result is not None
        except Exception as e:
            print(f"[alert] DB 조회 실패: {e}")

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

    if USE_DB:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO alert_history (id, rcept_no, rule_id, data, triggered_at)
                        VALUES (:id, :r, :rid, :data::jsonb, NOW())
                    """),
                    {
                        "id": record["id"],
                        "r": rcept_no,
                        "rid": rule_id,
                        "data": json.dumps(record, ensure_ascii=False),
                    },
                )
            return record
        except Exception as e:
            print(f"[alert] DB 저장 실패: {e}")

    records = _load()
    records.insert(0, record)
    _save(records[:_MAX_RECORDS])
    return record


def get_history(limit: int = 50) -> list[dict]:
    if USE_DB:
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("""
                        SELECT data FROM alert_history
                        ORDER BY triggered_at DESC
                        LIMIT :lim
                    """),
                    {"lim": limit},
                ).fetchall()
                return [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]
        except Exception as e:
            print(f"[alert] DB 조회 실패: {e}")

    return _load()[:limit]


def get_last_checked_at() -> str | None:
    """마지막 알림 점검 시각 반환 (ISO 8601)"""
    if USE_DB:
        try:
            with engine.connect() as conn:
                result = conn.execute(
                    text("SELECT value FROM alert_meta WHERE key = 'last_checked_at'")
                ).fetchone()
                return result[0] if result else None
        except Exception as e:
            print(f"[alert] DB 조회 실패: {e}")

    try:
        meta_path = _STORE_PATH.replace("alert_history.json", "alert_meta.json")
        with open(meta_path, encoding="utf-8") as f:
            return json.load(f).get("last_checked_at")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def set_last_checked_at(dt: datetime) -> None:
    if USE_DB:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO alert_meta (key, value)
                        VALUES ('last_checked_at', :v)
                        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
                    """),
                    {"v": dt.isoformat()},
                )
            return
        except Exception as e:
            print(f"[alert] DB 저장 실패: {e}")

    meta_path = _STORE_PATH.replace("alert_history.json", "alert_meta.json")
    os.makedirs(os.path.dirname(meta_path), exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump({"last_checked_at": dt.isoformat()}, f)
