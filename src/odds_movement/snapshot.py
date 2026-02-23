"""Snapshot Monday moneyline odds for upcoming PL fixtures (Bet365)."""

from __future__ import annotations

import json
import os
from datetime import date, datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
load_dotenv(".env.local", override=False)

import psycopg2
from psycopg2.extras import RealDictCursor

OUTPUT_DIR = Path("output/odds_movement")

QUERY = """\
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


def _connect():
    db_url = os.environ.get("SUPABASE_DB_URL", "")
    if not db_url:
        raise RuntimeError("SUPABASE_DB_URL is not set")
    return psycopg2.connect(db_url)


def take_snapshot() -> Path:
    conn = _connect()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(QUERY)
            rows = cur.fetchall()
    finally:
        conn.close()

    snapshot = []
    for row in rows:
        starting_at = row["starting_at"]
        if isinstance(starting_at, datetime):
            starting_at = starting_at.isoformat()
        snapshot.append(
            {
                "fixture_id": row["fixture_id"],
                "starting_at": starting_at,
                "home_team": row["home_team"],
                "away_team": row["away_team"],
                "selection_key": row["selection_key"],
                "price_decimal": float(row["price_decimal"]),
            }
        )

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    out_path = OUTPUT_DIR / f"{today}_monday_snapshot.json"
    out_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"Snapshot saved: {out_path} ({len(snapshot)} rows)")
    return out_path


if __name__ == "__main__":
    take_snapshot()
