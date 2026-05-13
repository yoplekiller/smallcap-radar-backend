"""PWA Web Push + FCM 구독 관리 API."""
from fastapi import APIRouter
from pydantic import BaseModel

from app.services.push_service import (
    VAPID_PUBLIC_KEY,
    add_subscription,
    remove_subscription,
    send_web_push,
    subscription_count,
)
from app.services.fcm_service import (
    register_token,
    unregister_token,
    send_fcm,
    token_count,
)

router = APIRouter(prefix="/push", tags=["push"])


class PushSubscription(BaseModel):
    endpoint: str
    keys: dict
    expirationTime: float | None = None


class FcmTokenBody(BaseModel):
    token: str


# ── Web Push (브라우저 PWA) ───────────────────────────────────────────────────

@router.get("/vapid-public-key")
async def get_vapid_public_key():
    return {"publicKey": VAPID_PUBLIC_KEY}


@router.post("/subscribe")
async def subscribe(sub: PushSubscription):
    add_subscription(sub.model_dump())
    return {"ok": True, "total": subscription_count()}


@router.post("/unsubscribe")
async def unsubscribe(body: dict):
    remove_subscription(body.get("endpoint", ""))
    return {"ok": True}


# ── FCM (Android 앱) ─────────────────────────────────────────────────────────

@router.post("/fcm-token")
async def register_fcm_token(body: FcmTokenBody):
    register_token(body.token)
    return {"ok": True, "total": token_count()}


@router.post("/fcm-unsubscribe")
async def unregister_fcm_token(body: FcmTokenBody):
    unregister_token(body.token)
    return {"ok": True}


# ── 테스트 ───────────────────────────────────────────────────────────────────

@router.post("/test")
async def test_push():
    web = await send_web_push(
        title="소형주 공시 레이더",
        body="푸시 알림 테스트 - 세력 포착 알림이 이렇게 옵니다!",
        url="/",
    )
    fcm = await send_fcm(
        title="소형주 공시 레이더",
        body="푸시 알림 테스트 - 세력 포착 알림이 이렇게 옵니다!",
    )
    return {"web_push": web, "fcm": fcm}
