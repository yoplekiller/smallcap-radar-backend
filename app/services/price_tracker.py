"""D+1 / D+5 / D+10 주가 성과 추적 — 세력 포착 알림 발생 후 주가 변동 자동 기록."""
from datetime import datetime, timezone

from app.services.alert_store import _load, _save
from app.services.market_cap_service import fetch_stock_price

_CHECKPOINTS = [("d1", 1), ("d5", 5), ("d10", 10)]


async def run_price_tracking() -> dict:
    """alert_history.json 순회하며 D+1/D+5/D+10 주가 업데이트."""
    records = _load()
    now = datetime.now(timezone.utc)
    updated_count = 0

    for record in records:
        stock_code = record.get("stock_code", "")
        trigger_price = record.get("stock_price")
        triggered_at_str = record.get("triggered_at", "")

        if not stock_code or not trigger_price or not triggered_at_str:
            continue

        try:
            triggered_dt = datetime.fromisoformat(triggered_at_str)
            if triggered_dt.tzinfo is None:
                triggered_dt = triggered_dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        days_elapsed = (now - triggered_dt).days
        tracking = record.setdefault("price_tracking", {})
        needs_update = any(
            days_elapsed >= min_d and label not in tracking
            for label, min_d in _CHECKPOINTS
        )
        if not needs_update:
            continue

        try:
            info = await fetch_stock_price(stock_code)
        except Exception:
            continue

        if not info or not info.get("price"):
            continue

        current_price = info["price"]

        for label, min_days in _CHECKPOINTS:
            if days_elapsed >= min_days and label not in tracking:
                change_pct = round((current_price - trigger_price) / trigger_price * 100, 2)
                tracking[label] = {
                    "price": current_price,
                    "change_pct": change_pct,
                    "tracked_at": now.isoformat(),
                }
                updated_count += 1

    if updated_count:
        _save(records)

    print(f"[price_tracker] 업데이트: {updated_count}건")
    return {"updated": updated_count}
