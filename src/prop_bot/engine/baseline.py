from __future__ import annotations

from typing import Dict

from src.prop_bot.db import db_cursor


def calculate_player_baseline(player_id: int, stat_type_id: int, league_id: int) -> Dict | None:
    query = """
        with player_game_log as (
            select
                fps.fixture_id,
                f.starting_at,
                f.home_team_id,
                f.away_team_id,
                fps.team_id,
                extract(epoch from (now() - f.starting_at)) / 86400.0 as days_ago,
                max(case when fps.type_id = %s then fps.value else 0 end) as stat_value,
                max(case when fps.type_id = 119 then fps.value else 0 end) as minutes_played
            from fixture_player_statistics fps
            join fixtures f on fps.fixture_id = f.id
            where fps.player_id = %s
              and f.league_id = %s
              and f.home_score is not null
              and f.away_score is not null
              and f.starting_at < now()
            group by fps.fixture_id, f.starting_at, f.home_team_id, f.away_team_id, fps.team_id
            order by f.starting_at desc
            limit 20
        )
        select
            sum(stat_value * exp(-0.023 * days_ago)) /
                nullif(sum((minutes_played / 90.0) * exp(-0.023 * days_ago)), 0) as weighted_per90,
            avg(stat_value) as simple_avg,
            (select avg(stat_value) from (
                select stat_value
                from player_game_log
                order by starting_at desc
                limit 5
            ) recent) as last_5_avg,
            count(*) as sample_size,
            sum(case when stat_value >= 1 then 1 else 0 end) as hit_1plus,
            sum(case when stat_value >= 2 then 1 else 0 end) as hit_2plus,
            sum(case when stat_value >= 3 then 1 else 0 end) as hit_3plus,
            sum(case when stat_value >= 4 then 1 else 0 end) as hit_4plus,
            avg(case when team_id = home_team_id then stat_value end) as home_avg,
            avg(case when team_id = away_team_id then stat_value end) as away_avg,
            count(case when team_id = home_team_id then 1 end) as home_games,
            count(case when team_id = away_team_id then 1 end) as away_games,
            stddev(stat_value) as std_dev,
            stddev(stat_value) / nullif(avg(stat_value), 0) as coeff_of_variation,
            avg(minutes_played) as avg_minutes,
            min(minutes_played) as min_minutes,
            sum(case when minutes_played < 70 then 1 else 0 end) as times_subbed_early,
            array_agg(stat_value order by starting_at desc) as raw_values,
            array_agg(minutes_played order by starting_at desc) as raw_minutes
        from player_game_log;
    """
    with db_cursor() as cur:
        cur.execute(query, (stat_type_id, player_id, league_id))
        row = cur.fetchone()
    if not row or row["sample_size"] is None:
        return None
    sample_size = int(row["sample_size"] or 0)
    if sample_size == 0:
        return None
    return {
        "weighted_per90": float(row["weighted_per90"] or 0.0),
        "simple_avg": float(row["simple_avg"] or 0.0),
        "last_5_avg": float(row["last_5_avg"] or 0.0),
        "sample_size": sample_size,
        "hit_rates": {
            "1+": int(row["hit_1plus"] or 0),
            "2+": int(row["hit_2plus"] or 0),
            "3+": int(row["hit_3plus"] or 0),
            "4+": int(row["hit_4plus"] or 0),
        },
        "home_avg": float(row["home_avg"] or 0.0),
        "away_avg": float(row["away_avg"] or 0.0),
        "home_games": int(row["home_games"] or 0),
        "away_games": int(row["away_games"] or 0),
        "std_dev": float(row["std_dev"] or 0.0),
        "coeff_of_variation": float(row["coeff_of_variation"] or 0.0),
        "avg_minutes": float(row["avg_minutes"] or 0.0),
        "min_minutes": float(row["min_minutes"] or 0.0),
        "times_subbed_early": int(row["times_subbed_early"] or 0),
        "raw_values": list(row["raw_values"] or []),
        "raw_minutes": list(row["raw_minutes"] or []),
        "trend": "improving" if (row["last_5_avg"] or 0) > (row["simple_avg"] or 0) else "flat",
    }
