from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict

from src.prop_bot.db import db_cursor


def get_player_team_share(
    player_id: int,
    team_id: int,
    stat_type_id: int,
    league_id: int,
) -> Dict | None:
    cutoff = datetime.utcnow() - timedelta(days=120)
    query = """
        with player_team_share as (
            select
                f.id as fixture_id,
                max(case when fps.player_id = %s and fps.type_id = %s then fps.value else 0 end) as player_stat,
                sum(case when fps.team_id = %s and fps.type_id = %s then fps.value else 0 end) as team_total
            from fixtures f
            join fixture_player_statistics fps on f.id = fps.fixture_id
            where f.league_id = %s
              and f.starting_at >= %s
              and f.home_score is not null
              and f.away_score is not null
              and (f.home_team_id = %s or f.away_team_id = %s)
            group by f.id
            order by f.starting_at desc
            limit 15
        )
        select avg(player_stat::float / nullif(team_total, 0)) as player_share
        from player_team_share
        where player_stat is not null and player_stat > 0;
    """
    with db_cursor() as cur:
        cur.execute(
            query,
            (
                player_id,
                stat_type_id,
                team_id,
                stat_type_id,
                league_id,
                cutoff,
                team_id,
                team_id,
            ),
        )
        row = cur.fetchone()
    if not row or row["player_share"] is None:
        return None
    return {"player_share": float(row["player_share"])}
