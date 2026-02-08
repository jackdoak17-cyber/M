from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict

from src.prop_bot.db import db_cursor


def _effective_stat_type_id(stat_type_id: int) -> int:
    # Mirror fouls markets for opponent context: committed -> drawn, drawn -> committed.
    if stat_type_id == 56:
        return 96
    if stat_type_id == 96:
        return 56
    return stat_type_id


def get_opponent_profile(opponent_team_id: int, stat_type_id: int, league_id: int) -> Dict | None:
    cutoff = datetime.utcnow() - timedelta(days=120)
    effective_stat_type_id = _effective_stat_type_id(stat_type_id)
    query = """
        with opponent_conceded as (
            select
                f.id as fixture_id,
                f.starting_at,
                sum(case when fps.team_id != %s and fps.type_id = %s then fps.value else 0 end) as stat_conceded
            from fixtures f
            join fixture_player_statistics fps on f.id = fps.fixture_id
            where (f.home_team_id = %s or f.away_team_id = %s)
              and f.league_id = %s
              and f.starting_at >= %s
              and f.home_score is not null
              and f.away_score is not null
            group by f.id, f.starting_at
            order by f.starting_at desc
            limit 15
        )
        select avg(stat_conceded) as avg_conceded, count(*) as sample_size
        from opponent_conceded;
    """
    with db_cursor() as cur:
        cur.execute(
            query,
            (opponent_team_id, effective_stat_type_id, opponent_team_id, opponent_team_id, league_id, cutoff),
        )
        row = cur.fetchone()
    if not row or row["sample_size"] is None or row["sample_size"] == 0:
        return None
    return {
        "avg_conceded": float(row["avg_conceded"] or 0.0),
        "sample_size": int(row["sample_size"] or 0),
    }


def get_league_average(stat_type_id: int, league_id: int) -> float:
    cutoff = datetime.utcnow() - timedelta(days=120)
    effective_stat_type_id = _effective_stat_type_id(stat_type_id)
    query = """
        with league_avg as (
            select f.id, sum(case when fps.type_id = %s then fps.value else 0 end) as total_stat
            from fixtures f
            join fixture_player_statistics fps on f.id = fps.fixture_id
            where f.league_id = %s
              and f.starting_at >= %s
              and f.home_score is not null
              and f.away_score is not null
            group by f.id
        )
        select avg(total_stat) / 2.0 as league_avg_per_team
        from league_avg;
    """
    with db_cursor() as cur:
        cur.execute(query, (effective_stat_type_id, league_id, cutoff))
        row = cur.fetchone()
    return float(row["league_avg_per_team"] or 0.0) if row else 0.0


def get_opponent_rank(opponent_team_id: int, stat_type_id: int, league_id: int) -> Dict:
    cutoff = datetime.utcnow() - timedelta(days=120)
    effective_stat_type_id = _effective_stat_type_id(stat_type_id)
    query = """
        with team_concessions as (
            select
                def_team_id,
                avg(stat_conceded) as avg_conceded
            from (
                select
                    f.id,
                    case
                        when f.home_team_id = fps.team_id then f.home_team_id
                        else f.away_team_id
                    end as def_team_id,
                    sum(case
                        when fps.team_id != case
                            when f.home_team_id = fps.team_id then f.home_team_id
                            else f.away_team_id
                        end
                        and fps.type_id = %s then fps.value else 0 end
                    ) as stat_conceded
                from fixtures f
                join fixture_player_statistics fps on f.id = fps.fixture_id
                where f.league_id = %s
                  and f.starting_at >= %s
                  and f.home_score is not null
                  and f.away_score is not null
                group by f.id, def_team_id
            ) sub
            group by def_team_id
        ),
        ranked as (
            select
                def_team_id,
                avg_conceded,
                rank() over (order by avg_conceded desc) as rank_most_conceded,
                rank() over (order by avg_conceded asc) as rank_fewest_conceded,
                count(*) over () as total_teams
            from team_concessions
        )
        select rank_most_conceded, rank_fewest_conceded, total_teams, avg_conceded
        from ranked
        where def_team_id = %s;
    """
    with db_cursor() as cur:
        cur.execute(query, (effective_stat_type_id, league_id, cutoff, opponent_team_id))
        row = cur.fetchone()
    if not row:
        return {}
    return {
        "rank_most_conceded": int(row["rank_most_conceded"]),
        "rank_fewest_conceded": int(row["rank_fewest_conceded"]),
        "total_teams": int(row["total_teams"]),
        "avg_conceded": float(row["avg_conceded"] or 0.0),
    }
