"""영속적 분석 결과 캐시 (data/analysis_cache.json).

서버 재시작 후에도 이전 분석 결과가 유지됩니다.
in-memory dict + JSON 파일 이중 저장 구조.
"""
import json
import os
from datetime import datetime, timezone

_CACHE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "analysis_cache.json"
)
_MAX_ENTRIES = 5_000   # 최대 5,000건 (약 2~3MB)

# 메모리 캐시 — 서버 시작 시 파일에서 로드됨
_mem: dict[str, dict] = {}
_dirty_count = 0        # 마지막 flush 이후 쓰기 횟수
_FLUSH_EVERY = 10       # 10건마다 파일에 저장


def load_from_disk() -> int:
    """서버 시작 시 1회 호출. 디스크 → 메모리 로드. 로드된 건수 반환."""
    global _mem
    try:
        with open(_CACHE_PATH, encoding="utf-8") as f:
            _mem.update(json.load(f))
        return len(_mem)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0


def get(rcept_no: str) -> dict | None:
    return _mem.get(rcept_no)


def has(rcept_no: str) -> bool:
    return rcept_no in _mem


def put(rcept_no: str, ai_result: dict) -> None:
    """분석 결과 저장 (메모리 + 주기적 파일 동기화)"""
    global _dirty_count
    _mem[rcept_no] = {
        **ai_result,
        "_cached_at": datetime.now(timezone.utc).isoformat(),
    }
    _dirty_count += 1
    if _dirty_count >= _FLUSH_EVERY:
        flush()


def flush() -> None:
    """메모리 캐시 전체를 파일에 저장"""
    global _dirty_count
    os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
    # 최신 MAX_ENTRIES개만 유지 (오래된 것 자동 제거)
    entries = list(_mem.items())[-_MAX_ENTRIES:]
    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(dict(entries), f, ensure_ascii=False)
    _dirty_count = 0


def stats() -> dict:
    return {
        "cached_count": len(_mem),
        "cache_path": _CACHE_PATH,
        "dirty_count": _dirty_count,
    }
