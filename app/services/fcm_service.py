"""FCM 푸시 알림 — firebase-admin SDK.

FIREBASE_SERVICE_ACCOUNT 환경변수(서비스 계정 JSON 문자열)가 있어야 발송 가능.
없으면 토큰 저장만 하고 발송은 건너뜀.
"""
import json
import os
from pathlib import Path

from sqlalchemy import text

from app.db import USE_DB, engine

# ── Firebase Admin 초기화 ─────────────────────────────────────────────────────
_fb_app = None

_sa_json = os.getenv("FIREBASE_SERVICE_ACCOUNT", "")
if _sa_json:
    try:
        import firebase_admin
        from firebase_admin import credentials

        _cred = credentials.Certificate(json.loads(_sa_json))
        _fb_app = firebase_admin.initialize_app(_cred)
        print("[fcm] Firebase Admin 초기화 완료")
    except Exception as e:
        print(f"[fcm] Firebase Admin 초기화 실패: {e}")
else:
    print("[fcm] FIREBASE_SERVICE_ACCOUNT 없음 → 발송 비활성화 (토큰 저장은 동작)")

# ── 파일 폴백 (로컬 개발) ─────────────────────────────────────────────────────
_TOKENS_FILE = Path(__file__).parent.parent.parent / "data" / "fcm_tokens.json"


def _file_get() -> list[str]:
    try:
        return json.loads(_TOKENS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def _file_save(tokens: list[str]) -> None:
    _TOKENS_FILE.parent.mkdir(exist_ok=True)
    _TOKENS_FILE.write_text(json.dumps(tokens, ensure_ascii=False), encoding="utf-8")


# ── 공개 API ─────────────────────────────────────────────────────────────────

def register_token(token: str) -> None:
    if USE_DB:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO fcm_tokens (token)
                        VALUES (:t)
                        ON CONFLICT (token) DO UPDATE SET updated_at = NOW()
                    """),
                    {"t": token},
                )
            return
        except Exception as e:
            print(f"[fcm] 토큰 저장 실패: {e}")

    tokens = _file_get()
    if token not in tokens:
        _file_save(tokens + [token])


def unregister_token(token: str) -> None:
    if USE_DB:
        try:
            with engine.begin() as conn:
                conn.execute(text("DELETE FROM fcm_tokens WHERE token = :t"), {"t": token})
            return
        except Exception as e:
            print(f"[fcm] 토큰 삭제 실패: {e}")

    _file_save([t for t in _file_get() if t != token])


def token_count() -> int:
    if USE_DB:
        try:
            with engine.connect() as conn:
                result = conn.execute(text("SELECT COUNT(*) FROM fcm_tokens")).fetchone()
                return result[0] if result else 0
        except Exception:
            pass
    return len(_file_get())


def _get_tokens() -> list[str]:
    if USE_DB:
        try:
            with engine.connect() as conn:
                rows = conn.execute(text("SELECT token FROM fcm_tokens")).fetchall()
                return [r[0] for r in rows]
        except Exception as e:
            print(f"[fcm] 토큰 조회 실패: {e}")
    return _file_get()


async def send_fcm(title: str, body: str, data: dict | None = None) -> dict[str, int]:
    """모든 등록된 FCM 토큰으로 알림 발송."""
    if _fb_app is None:
        return {"sent": 0, "failed": 0, "removed": 0}

    tokens = _get_tokens()
    if not tokens:
        return {"sent": 0, "failed": 0, "removed": 0}

    from firebase_admin import messaging

    sent = failed = removed = 0

    for token in tokens:
        try:
            messaging.send(messaging.Message(
                notification=messaging.Notification(title=title, body=body),
                data={k: str(v) for k, v in (data or {}).items()},
                android=messaging.AndroidConfig(
                    notification=messaging.AndroidNotification(
                        icon="ic_launcher",
                        color="#3B82F6",
                        sound="default",
                        channel_id="smallcap_alerts",
                    )
                ),
                token=token,
            ))
            sent += 1
        except messaging.UnregisteredError:
            unregister_token(token)
            removed += 1
        except Exception as e:
            print(f"[fcm] 전송 실패: {e}")
            failed += 1

    return {"sent": sent, "failed": failed, "removed": removed}
