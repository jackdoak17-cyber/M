from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List

from src.prop_bot.db import db_cursor


def get_performance_vs_similar(
    player_id: int,
    player_team_id: int,
    opponent_team_id: int,
    stat_type_id: int,
    threshold: int,
    league_id: int,
) -> Dict:
    cutoff = datetime.utcnow() - timedelta(days=365)
    tier_query = """
        with team_conceded as (
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
        tiers as (
            select
                def_team_id,
                avg_conceded,
                ntile(3) over (order by avg_conceded) as tier
            from team_conceded
        )
        select tier from tiers where def_team_id = %s;
    """
    with db_cursor() as cur:
        cur.execute(tier_query, (stat_type_id, league_id, cutoff, opponent_team_id))
        row = cur.fetchone()
    if not row:
        return {}
    tier = int(row["tier"])

    games_query = """
        select
            fps.fixture_id,
            max(case when fps.type_id = %s then fps.value else 0 end) as stat_value
        from fixture_player_statistics fps
        join fixtures f on fps.fixture_id = f.id
        where fps.player_id = %s
          and f.league_id = %s
          and f.starting_at >= %s
          and f.home_score is not null
          and f.away_score is not null
          and (
              case
                  when f.home_team_id = %s then f.away_team_id
                  else f.home_team_id
              end
          ) in (
              select def_team_id
              from (
                  select
                      def_team_id,
                      ntile(3) over (order by avg_conceded) as tier
                  from (
                      select
                          def_team_id,
                          avg(stat_conceded) as avg_conceded
                      from (
                          select
                              f2.id,
                              case
                                  when f2.home_team_id = fps2.team_id then f2.home_team_id
                                  else f2.away_team_id
                              end as def_team_id,
                              sum(case
                                  when fps2.team_id != case
                                      when f2.home_team_id = fps2.team_id then f2.home_team_id
                                      else f2.away_team_id
                                  end
                                  and fps2.type_id = %s then fps2.value else 0 end
                              ) as stat_conceded
                          from fixtures f2
                          join fixture_player_statistics fps2 on f2.id = fps2.fixture_id
                          where f2.league_id = %s
                            and f2.starting_at >= %s
                            and f2.home_score is not null
                            and f2.away_score is not null
                          group by f2.id, def_team_id
                      ) conceded
                      group by def_team_id
                  ) avg_conceded
              ) tiers
              where tier = %s
          )
        group by fps.fixture_id;
    """
    with db_cursor() as cur:
        cur.execute(
            games_query,
            (
                stat_type_id,
                player_id,
                league_id,
                cutoff,
                player_team_id,
                stat_type_id,
                league_id,
                cutoff,
                tier,
            ),
        )
        rows = cur.fetchall()

    values = [float(row["stat_value"] or 0.0) for row in rows]
    games = len(values)
    if games == 0:
        return {"opponent_tier": tier, "games_vs_similar": 0}
    hits = sum(1 for value in values if value >= threshold)

    examples_query = """
        select t.name
        from (
            select
                def_team_id,
                ntile(3) over (order by avg_conceded) as tier
            from (
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
                ) conceded
                group by def_team_id
            ) avg_conceded
        ) tiers
        join teams t on tiers.def_team_id = t.id
        where tier = %s
        order by t.name
        limit 3;
    """
    with db_cursor() as cur:
        cur.execute(examples_query, (stat_type_id, league_id, cutoff, tier))
        examples = [row["name"] for row in cur.fetchall()]

    return {
        "opponent_tier": tier,
        "games_vs_similar": games,
        "avg_vs_similar": sum(values) / games,
        "hitrate_vs_similar": round(hits / games * 100, 1),
        "similar_teams_examples": examples,
    }
