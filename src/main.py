from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Optional
from zoneinfo import ZoneInfo

from config import get_settings
from src import data_fetcher, formatter, player_analyzer, team_analyzer, weekend_player_props


settings = get_settings()


@dataclass(frozen=True)
class FixtureContext:
    fixture: data_fetcher.FixtureRow
    home_name: str
    away_name: str
    kickoff_time: str


def _resolve_team_name(team_row: Optional[dict], fallback_id: int) -> str:
    if not team_row:
        return f"Team {fallback_id}"
    return team_row.get("name") or team_row.get("short_code") or f"Team {fallback_id}"


def _resolve_player_name(player_row: Optional[dict], fallback_id: int) -> str:
    if not player_row:
        return f"Player {fallback_id}"
    return (
        player_row.get("display_name")
        or player_row.get("common_name")
        or player_row.get("short_name")
        or player_row.get("name")
        or f"Player {fallback_id}"
    )


def _format_kickoff(starting_at: datetime) -> str:
    local_tz = ZoneInfo(settings.timezone)
    if starting_at.tzinfo is None:
        starting_at = starting_at.replace(tzinfo=timezone.utc)
    local_time = starting_at.astimezone(local_tz)
    return local_time.strftime("%I:%M%p").lstrip("0").lower()


def _next_saturday(today: date) -> date:
    days_until = (5 - today.weekday()) % 7
    return today + timedelta(days=days_until)


def _parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def _get_team_starters(team_id: int) -> List[dict]:
    fixtures = data_fetcher.get_recent_team_fixtures(team_id, limit=1)
    if not fixtures:
        return []
    last_fixture_id = fixtures[0].id
    rows = data_fetcher.get_fixture_players([last_fixture_id], team_id)
    return [row for row in rows if row.get("is_starter")]


def _build_fixture_context(fixture: data_fetcher.FixtureRow) -> FixtureContext:
    teams = data_fetcher.get_teams_by_ids([fixture.home_team_id, fixture.away_team_id])
    home_name = _resolve_team_name(teams.get(fixture.home_team_id), fixture.home_team_id)
    away_name = _resolve_team_name(teams.get(fixture.away_team_id), fixture.away_team_id)
    kickoff_time = _format_kickoff(fixture.starting_at)
    return FixtureContext(
        fixture=fixture,
        home_name=home_name,
        away_name=away_name,
        kickoff_time=kickoff_time,
    )


def _collect_player_lines(team_id: int) -> List[formatter.PlayerStatLine]:
    starters = _get_team_starters(team_id)
    if not starters:
        return []
    sidelined_ids = set(data_fetcher.get_sidelined_player_ids(team_id))
    player_ids = [int(row["player_id"]) for row in starters if row.get("player_id") is not None]
    players = data_fetcher.get_players_by_ids(player_ids)

    lines: List[formatter.PlayerStatLine] = []
    for player_id in player_ids:
        stats_by_key = player_analyzer.get_qualifying_player_stats(
            player_id,
            team_id,
            sidelined_ids=sidelined_ids,
        )
        if not stats_by_key:
            continue
        player_name = _resolve_player_name(players.get(player_id), player_id)
        for stat_key, hits in stats_by_key.items():
            for hit in hits:
                lines.append(
                    formatter.PlayerStatLine(
                        player_name=player_name,
                        stat_key=stat_key,
                        threshold=hit.threshold,
                        wins=hit.wins,
                        total=hit.total,
                    ),
                )
    return lines


def _collect_team_lines(team_id: int, fixture_id: int) -> List[formatter.TeamStatLine]:
    hits = team_analyzer.get_qualifying_team_stats(team_id, fixture_id)
    if not hits:
        return []
    team = data_fetcher.get_teams_by_ids([team_id]).get(team_id)
    team_name = _resolve_team_name(team, team_id)
    return [
        formatter.TeamStatLine(
            team_name=team_name,
            stat_key=hit.stat_key,
            threshold=hit.threshold,
            wins=hit.wins,
            total=hit.total,
        )
        for hit in hits
    ]


def _build_fixture_section(fixture: data_fetcher.FixtureRow) -> str:
    context = _build_fixture_context(fixture)
    player_lines: List[formatter.PlayerStatLine] = []
    team_lines: List[formatter.TeamStatLine] = []

    for team_id in (fixture.home_team_id, fixture.away_team_id):
        player_lines.extend(_collect_player_lines(team_id))
        team_lines.extend(_collect_team_lines(team_id, fixture.id))

    return formatter.format_game_section(
        home_team=context.home_name,
        away_team=context.away_name,
        kickoff_time=context.kickoff_time,
        player_lines=player_lines,
        team_lines=team_lines,
    )


def generate_prop_sheet_for_day(day: date, day_label: str) -> str:
    fixtures = data_fetcher.get_fixtures_for_day(day)
    return generate_prop_sheet_for_fixtures(fixtures, day_label)


def generate_prop_sheet_for_fixtures(
    fixtures: Iterable[data_fetcher.FixtureRow],
    day_label: str,
) -> str:
    sections = [_build_fixture_section(fixture) for fixture in fixtures]
    return formatter.generate_full_prop_sheet(day_label, sections)


def generate_weekend_player_posts(day: date) -> tuple[str, str]:
    lines = weekend_player_props.collect_player_props_for_day(day)
    hundred, eighty = weekend_player_props.split_props_by_tier(lines)
    return (
        formatter.format_weekend_props_post(hundred, "100"),
        formatter.format_weekend_props_post(eighty, "80"),
    )


def generate_weekend_player_post_combined(day: date) -> str:
    lines = weekend_player_props.collect_player_props_for_day(day)
    hundred, eighty = weekend_player_props.split_props_by_tier(lines)
    return formatter.format_weekend_props_combined(hundred, eighty)


def _write_output(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main(args: Optional[Iterable[str]] = None) -> None:
    parser = argparse.ArgumentParser(description="Generate Premier League prop sheets.")
    parser.add_argument(
        "--saturday",
        help="Override scan start date (YYYY-MM-DD). Backward compatible alias.",
    )
    parser.add_argument(
        "--start-date",
        help="Start date for fixture scans (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to scan for fixtures.",
    )
    parser.add_argument(
        "--output-dir",
        default="output",
        help="Directory to write prop sheet files.",
    )
    parsed = parser.parse_args(args=args)

    today = datetime.now(ZoneInfo(settings.timezone)).date()
    override_date = _parse_date(parsed.saturday)
    start_date = _parse_date(parsed.start_date) or override_date or today
    day_count = max(parsed.days, 1)

    output_dir = Path(parsed.output_dir)
    by_fixture_dir = output_dir / "by_fixture"
    player_props_dir = output_dir / "player_props"
    for offset in range(day_count):
        day = start_date + timedelta(days=offset)
        fixtures = data_fetcher.get_fixtures_for_day(day)
        if not fixtures:
            continue
        day_label = day.strftime("%A")
        date_label = day.strftime("%Y-%m-%d")
        sheet = generate_prop_sheet_for_fixtures(fixtures, day_label)
        filename = f"{date_label}_{day_label.lower()}_prop_sheet_by_fixture.txt"
        _write_output(by_fixture_dir / filename, sheet)

        player_lines = weekend_player_props.collect_player_props_for_day(day)
        if not player_lines:
            continue
        hundred, eighty = weekend_player_props.split_props_by_tier(player_lines)
        total_100 = formatter.count_weekend_prop_lines(hundred)
        total_80 = formatter.count_weekend_prop_lines(eighty)
        combine_needed = total_100 < 24 or total_80 < 24
        if combine_needed and (total_100 > 0 or total_80 > 0):
            combined = formatter.format_weekend_props_combined(hundred, eighty)
            combined_name = f"{date_label}_{day_label.lower()}_player_props.txt"
            _write_output(player_props_dir / combined_name, combined)
            if day_label.lower() == "sunday":
                _write_output(
                    player_props_dir / f"{date_label}_sunday_player_props.txt",
                    combined,
                )
        else:
            if total_100 > 0:
                _write_output(
                    player_props_dir / f"{date_label}_{day_label.lower()}_player_props_100.txt",
                    formatter.format_weekend_props_post(hundred, "100"),
                )
            if total_80 > 0:
                _write_output(
                    player_props_dir / f"{date_label}_{day_label.lower()}_player_props_80.txt",
                    formatter.format_weekend_props_post(eighty, "80"),
                )


if __name__ == "__main__":
    main()
