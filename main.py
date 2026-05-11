import asyncio
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.disclosures import router as disclosures_router
from app.api.alerts import router as alerts_router, run_alert_check
from app.api.push import router as push_router
from app.services.price_tracker import run_price_tracking

_scheduler = AsyncIOScheduler(timezone="Asia/Seoul")


# ──────────────────────────────────────────────────────────────────────────────
# 자동 분석 Job — 스케줄러가 새 공시를 미리 분석해서 캐시에 저장
# ──────────────────────────────────────────────────────────────────────────────

async def auto_analyze_job(days: int = 1) -> None:
    """최근 N일 상장 공시를 자동 분석 후 캐시 저장.

    - 이미 캐시된 공시는 건너뜀 (토큰 낭비 없음)
    - stock_code 있는 공시만 분석 (시장 데이터 필요)
    - Groq TPM 초과 방지를 위해 요청 사이 1초 대기
    """
    from app.services.dart_service import fetch_recent_disclosures
    from app.services.market_cap_service import filter_small_cap_disclosures
    from app.services.ai_service import analyze_disclosure
    from app.services.analysis_cache import has as cache_has, flush

    disclosures = await fetch_recent_disclosures(days)

    # stock_code 있고 아직 미분석인 것만
    targets = [
        d for d in disclosures
        if d.get("stock_code", "").strip()
        and not cache_has(d.get("rcept_no", ""))
    ]

    analyzed = 0
    errors   = 0
    for d in targets:
        try:
            result = await analyze_disclosure(d)
            if result.get("ai") and not result["ai"].get("error"):
                analyzed += 1
        except Exception:
            errors += 1
        await asyncio.sleep(1)   # Groq RPM 제한 방어 (30 req/min 이내 유지)

    flush()   # 남은 dirty 항목 강제 저장
    print(f"[auto_analyze] 대상:{len(targets)} 분석완료:{analyzed} 에러:{errors}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ① 서버 시작 시 영속 캐시 로드 (파일 → 메모리)
    from app.services.analysis_cache import load_from_disk
    loaded = load_from_disk()
    print(f"[cache] 영속 캐시 {loaded}건 로드 완료")

    # ② 공시 자동 분석: 30분마다
    _scheduler.add_job(
        auto_analyze_job,
        "interval",
        minutes=30,
        id="auto_analyze",
        replace_existing=True,
        kwargs={"days": 1},
    )

    # ③ 알림 엔진: 15분마다
    _scheduler.add_job(
        run_alert_check,
        "interval",
        minutes=15,
        id="alert_check",
        replace_existing=True,
        kwargs={"days": 1},
    )

    # ④ 주가 성과 추적: 6시간마다 (D+1/D+5/D+10)
    _scheduler.add_job(
        run_price_tracking,
        "interval",
        hours=6,
        id="price_tracking",
        replace_existing=True,
    )

    _scheduler.start()
    yield
    from app.services.analysis_cache import flush
    flush()   # 서버 종료 전 캐시 저장
    _scheduler.shutdown(wait=False)


# ──────────────────────────────────────────────────────────────────────────────
# FastAPI 앱
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(title="DART 공시 크롤러", version="0.3.0", lifespan=lifespan)

_default_origins = {"http://localhost:3000", "http://localhost", "capacitor://localhost", "https://localhost"}
_env_var = os.getenv("ALLOWED_ORIGINS", "")
_env_origins = {o.strip() for o in _env_var.split(",") if o.strip()} if _env_var else set()
_origins = list(_default_origins | _env_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(disclosures_router)
app.include_router(alerts_router)
app.include_router(push_router)


@app.get("/health")
async def health_check():
    from app.services.analysis_cache import stats
    return {
        "status": "ok",
        "scheduler": _scheduler.running,
        "cache": stats(),
    }
