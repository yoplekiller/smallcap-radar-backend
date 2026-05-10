"""Web Push 서비스 — VAPID 기반 브라우저 푸시 알림."""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from pywebpush import WebPushException, webpush

load_dotenv()

VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_PUBLIC_KEY = os.getenv("VAPID_PUBLIC_KEY", "")
_VAPID_CLAIMS = {"sub": os.getenv("VAPID_EMAIL", "mailto:admin@example.com")}

_SUBS_FILE = Path(__file__).parent.parent.parent / "data" / "push_subscriptions.json"


def _load() -> list[dict]:
    if _SUBS_FILE.exists():
        try:
            return json.loads(_SUBS_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save(subs: list[dict]) -> None:
    _SUBS_FILE.parent.mkdir(exist_ok=True)
    _SUBS_FILE.write_text(json.dumps(subs, ensure_ascii=False, indent=2), encoding="utf-8")


def add_subscription(sub: dict) -> None:
    subs = _load()
    endpoint = sub.get("endpoint", "")
    if not any(s.get("endpoint") == endpoint for s in subs):
        subs.append(sub)
        _save(subs)


def remove_subscription(endpoint: str) -> None:
    subs = [s for s in _load() if s.get("endpoint") != endpoint]
    _save(subs)


def subscription_count() -> int:
    return len(_load())


async def send_web_push(title: str, body: str, url: str = "/") -> dict[str, int]:
    subs = _load()
    if not subs or not VAPID_PRIVATE_KEY:
        return {"sent": 0, "failed": 0, "removed": 0}

    payload = json.dumps({"title": title, "body": body, "url": url})
    sent, failed, removed = 0, 0, 0
    dead: list[str] = []

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
                dead.append(sub.get("endpoint", ""))
                removed += 1
            else:
                failed += 1
        except Exception:
            failed += 1

    if dead:
        _save([s for s in subs if s.get("endpoint") not in dead])

    return {"sent": sent, "failed": failed, "removed": removed}
