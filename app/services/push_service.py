"""Web Push 서비스 — VAPID 기반 브라우저 푸시 알림."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from pywebpush import WebPushException, webpush
from sqlalchemy import text

from app.db import USE_DB, engine

load_dotenv()

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
_VAPID_CLAIMS = {"sub": os.getenv("VAPID_EMAIL", "mailto:admin@example.com")}

_SUBS_FILE = Path(__file__).parent.parent.parent / "data" / "push_subscriptions.json"


def _load() -> list[dict]:
    if USE_DB:
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT sub_data FROM push_subscriptions")
                ).fetchall()
                return [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]
        except Exception as e:
            print(f"[push] DB 로드 실패: {e}")

    if _SUBS_FILE.exists():
        try:
            return json.loads(_SUBS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_file(subs: list[dict]) -> None:
    _SUBS_FILE.parent.mkdir(exist_ok=True)
    _SUBS_FILE.write_text(json.dumps(subs, ensure_ascii=False, indent=2), encoding="utf-8")


def add_subscription(sub: dict) -> None:
    endpoint = sub.get("endpoint", "")
    if USE_DB:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO push_subscriptions (endpoint, sub_data)
                        VALUES (:ep, :data::jsonb)
                        ON CONFLICT (endpoint) DO UPDATE SET sub_data = EXCLUDED.sub_data
                    """),
                    {"ep": endpoint, "data": json.dumps(sub, ensure_ascii=False)},
                )
            return
        except Exception as e:
            print(f"[push] DB 저장 실패: {e}")

    subs = _load()
    if not any(s.get("endpoint") == endpoint for s in subs):
        subs.append(sub)
        _save_file(subs)


def remove_subscription(endpoint: str) -> None:
    if USE_DB:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM push_subscriptions WHERE endpoint = :ep"),
                    {"ep": endpoint},
                )
            return
        except Exception as e:
            print(f"[push] DB 삭제 실패: {e}")

    subs = [s for s in _load() if s.get("endpoint") != endpoint]
    _save_file(subs)


def subscription_count() -> int:
    return len(_load())


async def send_web_push(title: str, body: str, url: str = "/") -> dict[str, int]:
    subs = _load()
    if not subs or not VAPID_PRIVATE_KEY:
        return {"sent": 0, "failed": 0, "removed": 0}

    payload = json.dumps({"title": title, "body": body, "url": url})
    sent, failed, removed = 0, 0, 0

    for sub in subs:
        try:
            webpush(
                subscription_info=sub,
                data=payload,
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=_VAPID_CLAIMS,
            )
            sent += 1
        except WebPushException as e:
            if e.response is not None and e.response.status_code in (404, 410):
                remove_subscription(sub.get("endpoint", ""))
                removed += 1
            else:
                failed += 1
        except Exception:
            failed += 1

    return {"sent": sent, "failed": failed, "removed": removed}
