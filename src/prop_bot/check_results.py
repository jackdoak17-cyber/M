from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from src.prop_bot.db import db_cursor
from src.prop_bot.engine.output import update_summary


def _fixture_completed(fixture_id: int) -> bool:
    query = """
        select home_score, away_score
        from fixtures
        where id = %s;
    """
    with db_cursor() as cur:
        cur.execute(query, (fixture_id,))
        row = cur.fetchone()
    if not row:
        return False
    return row.get("home_score") is not None and row.get("away_score") is not None


def _fetch_player_stat(fixture_id: int, player_id: int, stat_type_id: int) -> float:
    query = """
        select value
        from fixture_player_statistics
        where fixture_id = %s
          and player_id = %s
          and type_id = %s
        limit 1;
    """
    with db_cursor() as cur:
        cur.execute(query, (fixture_id, player_id, stat_type_id))
        row = cur.fetchone()
    if not row:
        return 0.0
    return float(row.get("value") or 0.0)


def _update_file(path: Path) -> List[Dict]:
    data = json.loads(path.read_text())
    picks = data.get("picks", [])
    updated = False
    for pick in picks:
        result = pick.get("result") or {}
        if result.get("hit") is not None:
            continue
        fixture_id = pick.get("fixture_id")
        if not fixture_id or not _fixture_completed(fixture_id):
            continue
        actual_value = _fetch_player_stat(
            fixture_id,
            pick.get("player_id"),
            pick.get("stat_type_id"),
        )
        threshold = pick.get("threshold", 0)
        hit = actual_value >= threshold
        pick["result"] = {
            "actual_value": actual_value,
            "hit": hit,
            "checked_at": datetime.utcnow().isoformat(),
        }
        updated = True

    if updated:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    return picks


def main() -> None:
    picks_dir = Path("picks")
    if not picks_dir.exists():
        print("No picks directory found.")
        return
    all_picks: List[Dict] = []
    for path in sorted(picks_dir.glob("*.json")):
        if path.name == "SUMMARY.json":
            continue
        all_picks.extend(_update_file(path))
    if all_picks:
        update_summary(all_picks, output_dir="picks")


if __name__ == "__main__":
    main()
