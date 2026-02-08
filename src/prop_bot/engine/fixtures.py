from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from src.prop_bot.config import LEAGUES, get_settings
from src.prop_bot.db import db_cursor
from src.prop_bot.models import Fixture


def get_upcoming_fixtures() -> List[Fixture]:
    settings = get_settings()
    league_ids = tuple(LEAGUES.keys())
    if not league_ids:
        return []
    window_end = datetime.utcnow() + timedelta(hours=settings.lookahead_hours)
    query = """
        select f.id as fixture_id,
               f.starting_at,
               f.home_team_id,
               f.away_team_id,
               ht.name as home_team,
               at.name as away_team,
               f.league_id
        from fixtures f
        join teams ht on f.home_team_id = ht.id
        join teams at on f.away_team_id = at.id
        where f.league_id = any(%s)
          and f.starting_at >= now()
          and f.starting_at <= %s
          and f.home_score is null
          and f.away_score is null
        order by f.starting_at;
    """
    fixtures: List[Fixture] = []
    with db_cursor() as cur:
        cur.execute(query, (list(league_ids), window_end))
        for row in cur.fetchall():
            league_id = int(row["league_id"])
            fixtures.append(
                Fixture(
                    fixture_id=int(row["fixture_id"]),
                    starting_at=row["starting_at"],
                    home_team_id=int(row["home_team_id"]),
                    away_team_id=int(row["away_team_id"]),
                    home_team=row["home_team"],
                    away_team=row["away_team"],
                    league_id=league_id,
                    league_name=LEAGUES.get(league_id, f"League {league_id}"),
                ),
            )
    return fixtures
