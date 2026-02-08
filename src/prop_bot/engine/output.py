from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {key: _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    return value


def save_picks_to_file(picks: List[Dict], output_dir: str = "picks") -> str:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    date_str = datetime.utcnow().strftime("%Y-%m-%d")
    payload = {
        "date": date_str,
        "generated_at": datetime.utcnow().isoformat(),
        "picks_count": len(picks),
        "picks": _json_safe(picks),
    }
    payload = _json_safe(payload)
    filepath = Path(output_dir) / f"{date_str}.json"
    filepath.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=_json_safe))
    return str(filepath)


def load_all_picks(output_dir: str = "picks") -> List[Dict]:
    path = Path(output_dir)
    if not path.exists():
        return []
    all_picks: List[Dict] = []
    for file in sorted(path.glob("*.json")):
        if file.name == "SUMMARY.json":
            continue
        data = json.loads(file.read_text())
        all_picks.extend(data.get("picks", []))
    return all_picks


def update_summary(all_picks: List[Dict], output_dir: str = "picks") -> str:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    hits = [pick for pick in all_picks if pick.get("result", {}).get("hit") is True]

    by_tier: Dict[str, Dict] = {}
    for pick in all_picks:
        tier = pick.get("confidence", {}).get("tier", "UNKNOWN")
        bucket = by_tier.setdefault(tier, {"total": 0, "hits": 0, "pnl": 0.0})
        bucket["total"] += 1
        if pick.get("result", {}).get("hit"):
            bucket["hits"] += 1
            odds = pick.get("edge", {}).get("bookmaker_odds") or pick.get("odds") or 0
            bucket["pnl"] += (odds * 10) - 10
        else:
            bucket["pnl"] -= 10

    by_league: Dict[str, Dict] = {}
    for pick in all_picks:
        league = pick.get("league_name", "Unknown")
        bucket = by_league.setdefault(league, {"total": 0, "hits": 0, "pnl": 0.0})
        bucket["total"] += 1
        if pick.get("result", {}).get("hit"):
            bucket["hits"] += 1
            odds = pick.get("edge", {}).get("bookmaker_odds") or pick.get("odds") or 0
            bucket["pnl"] += (odds * 10) - 10
        else:
            bucket["pnl"] -= 10

    by_market: Dict[str, Dict] = {}
    for pick in all_picks:
        market = pick.get("market_label", "Unknown")
        bucket = by_market.setdefault(market, {"total": 0, "hits": 0, "pnl": 0.0})
        bucket["total"] += 1
        if pick.get("result", {}).get("hit"):
            bucket["hits"] += 1
            odds = pick.get("edge", {}).get("bookmaker_odds") or pick.get("odds") or 0
            bucket["pnl"] += (odds * 10) - 10
        else:
            bucket["pnl"] -= 10

    total_pnl = sum(bucket["pnl"] for bucket in by_market.values()) if by_market else 0.0
    summary = {
        "last_updated": datetime.utcnow().isoformat(),
        "total_picks": len(all_picks),
        "total_hits": len(hits),
        "overall_hit_rate": round(len(hits) / len(all_picks) * 100, 1) if all_picks else 0,
        "total_pnl": round(total_pnl, 2),
        "avg_odds": round(
            sum((pick.get("odds") or 0) for pick in all_picks) / len(all_picks), 2
        )
        if all_picks
        else 0,
        "by_confidence_tier": by_tier,
        "by_league": by_league,
        "by_market": by_market,
    }
    filepath = Path(output_dir) / "SUMMARY.json"
    filepath.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    return str(filepath)
