from __future__ import annotations

from typing import Optional, Sequence

from src.prop_bot.config import BOOKMAKER_IDS
from src.prop_bot.db import db_cursor


def _threshold_to_line(threshold: int) -> float:
    return float(threshold) - 0.5


def get_player_market_odds(
    fixture_id: int,
    player_id: int,
    market_key: str,
    threshold: int,
    bookmaker_ids: Sequence[int] = BOOKMAKER_IDS,
) -> Optional[float]:
    line = _threshold_to_line(threshold)
    query = """
        select price_decimal
        from odds_outcomes
        where fixture_id = %s
          and market_key = %s
          and participant_type = 'player'
          and participant_id = %s
          and line = %s
          and bookmaker_id = any(%s)
        order by price_decimal desc
        limit 1;
    """
    with db_cursor() as cur:
        cur.execute(query, (fixture_id, market_key, player_id, line, list(bookmaker_ids)))
        row = cur.fetchone()
    if not row:
        return None
    return float(row["price_decimal"] or 0.0)


def get_team_win_odds(
    fixture_id: int,
    team_id: int,
    is_home: bool,
    bookmaker_ids: Sequence[int] = BOOKMAKER_IDS,
) -> Optional[float]:
    query = """
        select price_decimal
        from odds_outcomes
        where fixture_id = %s
          and market_key = 'full_time_result'
          and participant_id = %s
          and bookmaker_id = any(%s)
        order by price_decimal desc
        limit 1;
    """
    with db_cursor() as cur:
        cur.execute(query, (fixture_id, team_id, list(bookmaker_ids)))
        row = cur.fetchone()
    if row and row["price_decimal"] is not None:
        return float(row["price_decimal"])

    selection_key = "home_home" if is_home else "away_away"
    fallback_query = """
        select price_decimal
        from odds_outcomes
        where fixture_id = %s
          and market_key = 'full_time_result'
          and selection_key = %s
          and bookmaker_id = any(%s)
        order by price_decimal desc
        limit 1;
    """
    with db_cursor() as cur:
        cur.execute(fallback_query, (fixture_id, selection_key, list(bookmaker_ids)))
        row = cur.fetchone()
    if not row:
        return None
    return float(row["price_decimal"] or 0.0)
