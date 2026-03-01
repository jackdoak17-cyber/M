from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Sequence
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import RealDictCursor

from config import get_settings


settings = get_settings()


@dataclass(frozen=True)
class FixtureRow:
    id: int
    starting_at: datetime
    home_team_id: int
    away_team_id: int
    home_score: Optional[int]
    away_score: Optional[int]


@contextmanager
def db_cursor():
    conn = psycopg2.connect(settings.supabase_db_url)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
    finally:
        conn.close()


def _to_utc_bounds(day: date, tz_name: str) -> tuple[datetime, datetime]:
    local_tz = ZoneInfo(tz_name)
    start_local = datetime.combine(day, time(0, 0, 0), tzinfo=local_tz)
    end_local = start_local + timedelta(days=1)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def get_fixtures_for_day(day: date, league_id: int = settings.premier_league_id) -> List[FixtureRow]:
    start_utc, end_utc = _to_utc_bounds(day, settings.timezone)
    query = """
        select id, starting_at, home_team_id, away_team_id, home_score, away_score
        from fixtures
        where league_id = %s
          and starting_at >= %s
          and starting_at < %s
        order by starting_at;
    """
    with db_cursor() as cur:
        cur.execute(query, (league_id, start_utc, end_utc))
        rows = cur.fetchall()
    fixtures: List[FixtureRow] = []
    for row in rows:
        fixtures.append(
            FixtureRow(
                id=int(row["id"]),
                starting_at=row["starting_at"],
                home_team_id=int(row["home_team_id"]),
                away_team_id=int(row["away_team_id"]),
                home_score=row.get("home_score"),
                away_score=row.get("away_score"),
            ),
        )
    return fixtures


def get_recent_team_fixtures(
    team_id: int,
    limit: int = 20,
    league_id: int = settings.premier_league_id,
) -> List[FixtureRow]:
    query = """
        select id, starting_at, home_team_id, away_team_id, home_score, away_score
        from fixtures
        where league_id = %s
          and (home_team_id = %s or away_team_id = %s)
          and home_score is not null
          and away_score is not null
          and starting_at < now()
        order by starting_at desc
        limit %s;
    """
    with db_cursor() as cur:
        cur.execute(query, (league_id, team_id, team_id, limit))
        rows = cur.fetchall()
    fixtures: List[FixtureRow] = []
    for row in rows:
        fixtures.append(
            FixtureRow(
                id=int(row["id"]),
                starting_at=row["starting_at"],
                home_team_id=int(row["home_team_id"]),
                away_team_id=int(row["away_team_id"]),
                home_score=row.get("home_score"),
                away_score=row.get("away_score"),
            ),
        )
    return fixtures


def get_fixture_players(
    fixture_ids: Sequence[int],
    team_id: int,
) -> List[Dict]:
    if not fixture_ids:
        return []
    query = """
        select fixture_id, player_id, team_id, is_starter, minutes_played,
               position_name, position_abbr, detailed_position_name,
               lineup_detailed_position_name
        from fixture_players
        where fixture_id = any(%s)
          and team_id = %s;
    """
    with db_cursor() as cur:
        cur.execute(query, (list(fixture_ids), team_id))
        return cur.fetchall()


def get_fixture_player_stats(
    fixture_ids: Sequence[int],
    player_ids: Sequence[int],
    type_ids: Sequence[int],
) -> List[Dict]:
    if not fixture_ids or not player_ids or not type_ids:
        return []
    query = """
        select fixture_id, player_id, type_id, value
        from fixture_player_statistics
        where fixture_id = any(%s)
          and player_id = any(%s)
          and type_id = any(%s);
    """
    with db_cursor() as cur:
        cur.execute(query, (list(fixture_ids), list(player_ids), list(type_ids)))
        return cur.fetchall()


def get_fixture_team_stats(
    fixture_ids: Sequence[int],
    team_id: int,
    type_ids: Sequence[int],
) -> List[Dict]:
    if not fixture_ids or not type_ids:
        return []
    query = """
        select fixture_id, team_id, type_id, value
        from fixture_statistics
        where fixture_id = any(%s)
          and team_id = %s
          and type_id = any(%s);
    """
    with db_cursor() as cur:
        cur.execute(query, (list(fixture_ids), team_id, list(type_ids)))
        return cur.fetchall()


def get_sidelined_player_ids(team_id: int) -> List[int]:
    query = """
        select distinct player_id
        from sidelined_active
        where team_id = %s
          and (completed is null or completed = false)
          and (end_date is null or end_date >= current_date);
    """
    with db_cursor() as cur:
        cur.execute(query, (team_id,))
        rows = cur.fetchall()
    return [int(row["player_id"]) for row in rows if row.get("player_id") is not None]


def get_players_by_ids(player_ids: Iterable[int]) -> Dict[int, Dict]:
    ids = list({int(pid) for pid in player_ids if pid is not None})
    if not ids:
        return {}
    query = """
        select id, name, short_name, common_name, display_name, team_id, image_path
        from players
        where id = any(%s);
    """
    with db_cursor() as cur:
        cur.execute(query, (ids,))
        rows = cur.fetchall()
    return {int(row["id"]): row for row in rows}


def get_teams_by_ids(team_ids: Iterable[int]) -> Dict[int, Dict]:
    ids = list({int(tid) for tid in team_ids if tid is not None})
    if not ids:
        return {}
    query = """
        select id, name, short_code, image_path
        from teams
        where id = any(%s);
    """
    with db_cursor() as cur:
        cur.execute(query, (ids,))
        rows = cur.fetchall()
    return {int(row["id"]): row for row in rows}


def get_bet365_team_line(
    fixture_id: int,
    team_id: int,
    market_key: str,
    bookmaker_id: int = settings.bet365_bookmaker_id,
) -> Optional[float]:
    query = """
        select line, last_updated_at
        from odds_outcomes
        where fixture_id = %s
          and participant_type = 'team'
          and participant_id = %s
          and market_key = %s
          and selection_key = any(%s)
          and bookmaker_id = %s
        order by last_updated_at desc
        limit 1;
    """
    over_keys = ["over", "home_over", "away_over"]
    with db_cursor() as cur:
        cur.execute(query, (fixture_id, team_id, market_key, over_keys, bookmaker_id))
        row = cur.fetchone()
    if not row:
        return None
    line = row.get("line")
    return float(line) if line is not None else None
