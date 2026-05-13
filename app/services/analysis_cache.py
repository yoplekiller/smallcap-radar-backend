"""영속적 분석 결과 캐시.

DATABASE_URL 환경변수 있으면 PostgreSQL, 없으면 로컬 파일 캐시 (로컬 개발용).
서버 재배포 후에도 분석 결과 유지.
"""
import json
import os
from datetime import datetime, timezone

from sqlalchemy import text

from app.db import USE_DB as _USE_DB, engine

# ── 파일 폴백 경로 (로컬 / DB 실패 시) ──────────────────────────────────────
_CACHE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "analysis_cache.json"
)
_MAX_ENTRIES = 5_000

# ── 인메모리 캐시 (빠른 읽기) ────────────────────────────────────────────────
_mem: dict[str, dict] = {}
_dirty_count = 0
_FLUSH_EVERY = 10


def _load_file() -> dict:
    try:
        with open(_CACHE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _migrate_file_to_db(data: dict) -> None:
    """파일 캐시 → DB 일괄 이전 (최초 1회)."""
    if not data:
        return
    try:
        with engine.begin() as conn:
            for rcept_no, entry in data.items():
                conn.execute(
                    text("""
                        INSERT INTO analysis_cache (rcept_no, data, cached_at)
                        VALUES (:k, :v::jsonb, NOW())
                        ON CONFLICT (rcept_no) DO NOTHING
                    """),
                    {"k": rcept_no, "v": json.dumps(entry, ensure_ascii=False)},
                )
        print(f"[cache] 파일 → DB 마이그레이션 완료 ({len(data)}건)")
    except Exception as e:
        print(f"[cache] 마이그레이션 실패: {e}")


def load_from_disk() -> int:
    """서버 시작 시 1회 호출. 저장소 → 메모리 로드."""
    global _mem
    if _USE_DB:
        try:
            with engine.connect() as conn:
                rows = conn.execute(
                    text("SELECT rcept_no, data FROM analysis_cache")
                ).fetchall()
                for rcept_no, data in rows:
                    _mem[rcept_no] = data if isinstance(data, dict) else json.loads(data)

            if not _mem:
                file_data = _load_file()
                if file_data:
                    _mem.update(file_data)
                    _migrate_file_to_db(file_data)

            return len(_mem)
        except Exception as e:
            print(f"[cache] DB 로드 실패, 파일 폴백: {e}")

    _mem.update(_load_file())
    return len(_mem)


def get(rcept_no: str) -> dict | None:
    return _mem.get(rcept_no)


def has(rcept_no: str) -> bool:
    return rcept_no in _mem


def put(rcept_no: str, ai_result: dict) -> None:
    global _dirty_count
    entry = {**ai_result, "_cached_at": datetime.now(timezone.utc).isoformat()}
    _mem[rcept_no] = entry

    if _USE_DB:
        try:
            with engine.begin() as conn:
                conn.execute(
                    text("""
                        INSERT INTO analysis_cache (rcept_no, data, cached_at)
                        VALUES (:k, :v::jsonb, NOW())
                        ON CONFLICT (rcept_no) DO UPDATE
                        SET data = EXCLUDED.data, cached_at = NOW()
                    """),
                    {"k": rcept_no, "v": json.dumps(entry, ensure_ascii=False)},
                )
        except Exception as e:
            print(f"[cache] DB 저장 실패 ({rcept_no}): {e}")
        return

    _dirty_count += 1
    if _dirty_count >= _FLUSH_EVERY:
        flush()


def flush() -> None:
    """서버 종료 시 호출. DB 모드에서는 put()에서 이미 저장되므로 no-op."""
    global _dirty_count
    _dirty_count = 0
    if _USE_DB:
        return
    os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
    entries = list(_mem.items())[-_MAX_ENTRIES:]
    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(dict(entries), f, ensure_ascii=False)


def stats() -> dict:
    return {
        "cached_count": len(_mem),
        "storage": "postgresql" if _USE_DB else "file",
        "dirty_count": _dirty_count,
    }
