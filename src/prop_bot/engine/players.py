from __future__ import annotations

from datetime import datetime, timedelta
from typing import List

from src.prop_bot.config import get_settings
from src.prop_bot.db import db_cursor
from src.prop_bot.models import EligiblePlayer, Fixture


def get_eligible_players(fixture: Fixture) -> List[EligiblePlayer]:
    settings = get_settings()
    cutoff = datetime.utcnow() - timedelta(days=120)
    query = """
        select
            fps.player_id,
            p.display_name as player_name,
            fps.team_id,
            t.name as team_name,
            count(distinct fps.fixture_id) as appearances
        from fixture_player_statistics fps
        join fixtures f on fps.fixture_id = f.id
        join players p on fps.player_id = p.id
        join teams t on fps.team_id = t.id
        where fps.team_id = any(%s)
          and f.league_id = %s
          and f.starting_at >= %s
          and f.home_score is not null
          and f.away_score is not null
        group by fps.player_id, p.display_name, fps.team_id, t.name
        having count(distinct fps.fixture_id) >= %s
        order by appearances desc;
    """
    team_ids = [fixture.home_team_id, fixture.away_team_id]
    players: List[EligiblePlayer] = []
    with db_cursor() as cur:
        cur.execute(query, (team_ids, fixture.league_id, cutoff, settings.min_appearances))
        for row in cur.fetchall():
            players.append(
                EligiblePlayer(
                    player_id=int(row["player_id"]),
                    player_name=row["player_name"] or "Unknown",
                    team_id=int(row["team_id"]),
                    team_name=row["team_name"],
                    appearances=int(row["appearances"]),
                ),
            )
    return players
