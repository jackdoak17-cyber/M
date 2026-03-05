from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List

from src import data_fetcher
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


def player_is_currently_sidelined(
    player_id: int,
    team_id: int,
    on_date: date,
    *,
    lookback_days: int = 365,
) -> bool:
    """Return True when a recent injury/suspension record is active for the player."""
    if player_id in data_fetcher.get_manual_excluded_player_ids(on_date=on_date):
        return True
    lookback_start = on_date - timedelta(days=lookback_days)
    query = """
        select 1
        from sidelined_active
        where player_id = %s
          and (
                team_id = %s
                or exists (
                    select 1
                    from players p
                    where p.id = sidelined_active.player_id
                      and p.team_id = %s
                )
              )
          and lower(coalesce(category, '')) in ('injury', 'suspended', 'suspension')
          and coalesce(completed, false) = false
          and start_date <= %s
          and (end_date is null or end_date >= %s)
          and start_date >= %s
        limit 1;
    """
    with db_cursor() as cur:
        cur.execute(query, (player_id, team_id, team_id, on_date, on_date, lookback_start))
        return cur.fetchone() is not None


def player_started_last_completed_team_match(
    player_id: int,
    team_id: int,
    league_id: int,
    reference_time: datetime,
) -> bool:
    """
    Return True only if player started the team's most recent completed league match.

    Falls back to minutes-played stat when fixture lineups are missing.
    """
    query = """
        with last_fixture as (
            select id
            from fixtures
            where league_id = %s
              and starting_at < %s
              and home_score is not null
              and away_score is not null
              and (home_team_id = %s or away_team_id = %s)
            order by starting_at desc
            limit 1
        ),
        lineup as (
            select fp.is_starter, fp.minutes_played
            from fixture_players fp
            join last_fixture lf on lf.id = fp.fixture_id
            where fp.player_id = %s
              and fp.team_id = %s
            limit 1
        ),
        stat_minutes as (
            select max(case when fps.type_id = 119 then fps.value end) as minutes_played
            from fixture_player_statistics fps
            join last_fixture lf on lf.id = fps.fixture_id
            where fps.player_id = %s
              and fps.team_id = %s
        )
        select
            (select id from last_fixture) as fixture_id,
            (select is_starter from lineup) as is_starter,
            (select minutes_played from lineup) as lineup_minutes,
            (select minutes_played from stat_minutes) as stat_minutes;
    """
    with db_cursor() as cur:
        cur.execute(
            query,
            (
                league_id,
                reference_time,
                team_id,
                team_id,
                player_id,
                team_id,
                player_id,
                team_id,
            ),
        )
        row = cur.fetchone()

    if not row or row["fixture_id"] is None:
        # No prior completed match for this team in-league; do not block.
        return True

    if row["is_starter"] is True:
        return True
    if row["is_starter"] is False:
        return False

    stat_minutes = row["stat_minutes"]
    if stat_minutes is not None:
        return float(stat_minutes) >= 60.0
    lineup_minutes = row["lineup_minutes"]
    if lineup_minutes is not None:
        return float(lineup_minutes) >= 60.0
    return False


def player_is_defender(
    player_id: int,
    team_id: int,
    league_id: int,
    reference_time: datetime,
) -> bool:
    """Infer whether the player's recent position is defensive."""
    query = """
        select
            fp.position_name,
            fp.position_abbr,
            fp.detailed_position_name,
            fp.detailed_position_code,
            fp.lineup_detailed_position_name,
            fp.lineup_detailed_position_code
        from fixture_players fp
        join fixtures f on f.id = fp.fixture_id
        where fp.player_id = %s
          and fp.team_id = %s
          and f.league_id = %s
          and f.starting_at < %s
          and f.home_score is not null
          and f.away_score is not null
        order by f.starting_at desc
        limit 1;
    """
    with db_cursor() as cur:
        cur.execute(query, (player_id, team_id, league_id, reference_time))
        row = cur.fetchone()
    if not row:
        return False

    abbr = str(row.get("position_abbr") or "").strip().upper()
    if abbr in {"D", "CB", "LB", "RB", "LCB", "RCB", "LWB", "RWB", "SW"}:
        return True

    for field in (
        row.get("position_name"),
        row.get("detailed_position_name"),
        row.get("detailed_position_code"),
        row.get("lineup_detailed_position_name"),
        row.get("lineup_detailed_position_code"),
    ):
        text = str(field or "").strip().lower()
        if not text:
            continue
        if text == "defender":
            return True
        if any(
            token in text
            for token in (
                "center back",
                "centre back",
                "center-back",
                "centre-back",
                "left back",
                "right back",
                "left-back",
                "right-back",
                "full back",
                "full-back",
                "wing back",
                "wing-back",
            )
        ):
            return True
    return False
