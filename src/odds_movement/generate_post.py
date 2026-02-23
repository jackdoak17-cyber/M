"""Generate odds movement post comparing Monday snapshot to matchday odds."""

from __future__ import annotations

import json
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()
load_dotenv(".env.local", override=False)

import psycopg2
from psycopg2.extras import RealDictCursor

OUTPUT_DIR = Path("output/odds_movement")

CURRENT_ODDS_QUERY = """\
SELECT oo.fixture_id, f.starting_at,
       ht.name AS home_team, at.name AS away_team,
       oo.selection_key, oo.price_decimal
FROM odds_outcomes oo
JOIN fixtures f ON f.id = oo.fixture_id
JOIN teams ht ON ht.id = f.home_team_id
JOIN teams at ON at.id = f.away_team_id
WHERE oo.market_key = 'moneyline'
  AND oo.bookmaker_id = 2
  AND f.league_id = 8
  AND f.starting_at BETWEEN now() AND now() + interval '7 days'
ORDER BY f.starting_at, oo.selection_key
"""

SELECTION_ORDER = {"Home": 0, "Draw": 1, "Away": 2}


def _connect():
    db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        raise RuntimeError("SUPABASE_DB_URL is not set")
    return psycopg2.connect(db_url)


def _find_monday_snapshot(target: date) -> Path:
    """Find the most recent Monday snapshot on or before target date."""
    # Walk back to the most recent Monday
    days_since_monday = target.weekday()  # Monday=0
    monday = target - timedelta(days=days_since_monday)

    path = OUTPUT_DIR / f"{monday.isoformat()}_monday_snapshot.json"
    if path.exists():
        return path

    # Try previous Monday if current Monday's snapshot isn't there
    prev_monday = monday - timedelta(days=7)
    prev_path = OUTPUT_DIR / f"{prev_monday.isoformat()}_monday_snapshot.json"
    if prev_path.exists():
        return prev_path

    raise FileNotFoundError(
        f"No Monday snapshot found at {path} or {prev_path}"
    )


def _arrow(old: float, new: float) -> str:
    if new > old:
        return "\u2191"
    if new < old:
        return "\u2193"
    return "\u2014"


def _day_name(target: date) -> str:
    return target.strftime("%a")


def generate_post(target: date | None = None) -> Path:
    tz = ZoneInfo(os.environ.get("PROP_SHEET_TIMEZONE", "Europe/London"))

    if target is None:
        target = datetime.now(tz).date()

    snapshot_path = _find_monday_snapshot(target)
    snapshot_data = json.loads(snapshot_path.read_text(encoding="utf-8"))

    # Index Monday odds: (fixture_id, selection_key) -> price
    monday_odds: dict[tuple[int, str], float] = {}
    monday_fixtures: dict[int, dict] = {}
    for row in snapshot_data:
        key = (row["fixture_id"], row["selection_key"])
        monday_odds[key] = row["price_decimal"]
        monday_fixtures[row["fixture_id"]] = {
            "home_team": row["home_team"],
            "away_team": row["away_team"],
            "starting_at": row["starting_at"],
        }

    # Fetch current odds
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(CURRENT_ODDS_QUERY)
            current_rows = cur.fetchall()
    finally:
        conn.close()

    # Group current odds by fixture
    current_by_fixture: dict[int, dict[str, float]] = defaultdict(dict)
    fixture_meta: dict[int, dict] = {}
    for row in current_rows:
        fid = row["fixture_id"]
        current_by_fixture[fid][row["selection_key"]] = float(row["price_decimal"])
        if fid not in fixture_meta:
            starting_at = row["starting_at"]
            if isinstance(starting_at, str):
                starting_at = datetime.fromisoformat(starting_at)
            fixture_meta[fid] = {
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "starting_at": starting_at,
            }

    # Filter to fixtures on the target day
    target_fixtures = []
    for fid, meta in fixture_meta.items():
        kick_off = meta["starting_at"]
        if hasattr(kick_off, "astimezone"):
            kick_off_local = kick_off.astimezone(tz)
        else:
            kick_off_local = kick_off
        if kick_off_local.date() == target:
            target_fixtures.append((fid, meta, kick_off_local))

    target_fixtures.sort(key=lambda x: x[2])

    if not target_fixtures:
        print(f"No fixtures found for {target}")
        return OUTPUT_DIR / f"{target.isoformat()}_odds_movement.txt"

    day_label = _day_name(target)
    lines = [f"\U0001f4c8 PL Odds Movement | Mon \u2192 {day_label}", ""]

    for fid, meta, kick_off_local in target_fixtures:
        home = meta["home_team"]
        away = meta["away_team"]
        time_str = kick_off_local.strftime("%-I:%M%p").lower()
        lines.append(f"{home} vs {away} - {time_str}")

        current = current_by_fixture.get(fid, {})
        for selection in ["Home", "Draw", "Away"]:
            label = home if selection == "Home" else (away if selection == "Away" else "Draw")
            mon_price = monday_odds.get((fid, selection))
            cur_price = current.get(selection)
            if mon_price is not None and cur_price is not None:
                arrow = _arrow(mon_price, cur_price)
                lines.append(
                    f"\u2022 {label}: {mon_price:.2f} \u2192 {cur_price:.2f} {arrow}"
                )

        lines.append("")

    lines.append("via Bet365")

    post_text = "\n".join(lines)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{target.isoformat()}_odds_movement.txt"
    out_path.write_text(post_text, encoding="utf-8")
    print(f"Post saved: {out_path}")
    print(post_text)
    return out_path


if __name__ == "__main__":
    generate_post()
