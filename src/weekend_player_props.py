from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List

from src import data_fetcher


TYPE_SHOTS_TOTAL = 42
TYPE_SHOTS_ON_TARGET = 86
TYPE_FOULS_COMMITTED = 56
TYPE_FOULS_DRAWN = 96

STAT_TYPE_MAP = {
    "shots": TYPE_SHOTS_TOTAL,
    "shots_on_target": TYPE_SHOTS_ON_TARGET,
    "fouls_committed": TYPE_FOULS_COMMITTED,
    "fouls_drawn": TYPE_FOULS_DRAWN,
}


@dataclass(frozen=True)
class PlayerPropLine:
    player_name: str
    team_name: str
    stat_key: str
    threshold: int
    values: List[float]
    wins: int
    total: int

    @property
    def rate(self) -> float:
        return self.wins / self.total if self.total else 0.0


def _resolve_team_name(team_row: Dict | None, fallback_id: int) -> str:
    if not team_row:
        return f"Team {fallback_id}"
    return team_row.get("name") or team_row.get("short_code") or f"Team {fallback_id}"


def _resolve_player_name(player_row: Dict | None, fallback_id: int) -> str:
    if not player_row:
        return f"Player {fallback_id}"
    return (
        player_row.get("display_name")
        or player_row.get("common_name")
        or player_row.get("short_name")
        or player_row.get("name")
        or f"Player {fallback_id}"
    )


def _collect_team_lines(team_id: int) -> List[PlayerPropLine]:
    fixtures = data_fetcher.get_recent_team_fixtures(team_id, limit=20)
    if not fixtures:
        return []

    fixture_ids = [fixture.id for fixture in fixtures]
    player_rows = data_fetcher.get_fixture_players(fixture_ids, team_id)
    if not player_rows:
        return []

    last_fixture_id = fixture_ids[0]
    last_starters = {
        int(row["player_id"])
        for row in player_rows
        if row.get("player_id") is not None
        and int(row["fixture_id"]) == last_fixture_id
        and row.get("is_starter")
    }
    if not last_starters:
        return []

    sidelined_ids = set(data_fetcher.get_sidelined_player_ids(team_id))
    candidate_ids = {pid for pid in last_starters if pid not in sidelined_ids}
    if not candidate_ids:
        return []

    rows_by_fixture: Dict[int, List[Dict]] = {}
    for row in player_rows:
        fixture_id = int(row["fixture_id"])
        rows_by_fixture.setdefault(fixture_id, []).append(row)

    started_by_player: Dict[int, List[int]] = {pid: [] for pid in candidate_ids}
    for fixture in fixtures:
        for row in rows_by_fixture.get(fixture.id, []):
            player_id = row.get("player_id")
            if player_id is None:
                continue
            player_id = int(player_id)
            if player_id not in started_by_player:
                continue
            if row.get("is_starter"):
                started_by_player[player_id].append(fixture.id)

    last_five_by_player = {
        pid: starts[:5]
        for pid, starts in started_by_player.items()
        if len(starts) >= 5
    }
    if not last_five_by_player:
        return []

    fixture_ids_needed = sorted(
        {fixture_id for starts in last_five_by_player.values() for fixture_id in starts},
    )
    player_ids = list(last_five_by_player.keys())
    stats_rows = data_fetcher.get_fixture_player_stats(
        fixture_ids_needed,
        player_ids,
        list(STAT_TYPE_MAP.values()),
    )
    stats_map = {
        (int(row["fixture_id"]), int(row["player_id"]), int(row["type_id"])): float(row["value"])
        for row in stats_rows
    }

    team_name = _resolve_team_name(
        data_fetcher.get_teams_by_ids([team_id]).get(team_id),
        team_id,
    )
    players = data_fetcher.get_players_by_ids(player_ids)

    lines: List[PlayerPropLine] = []
    for player_id, start_ids in last_five_by_player.items():
        player_name = _resolve_player_name(players.get(player_id), player_id)
        for stat_key, type_id in STAT_TYPE_MAP.items():
            values_list = [
                stats_map.get((fixture_id, player_id, type_id), 0.0)
                for fixture_id in start_ids
            ]
            wins_1 = sum(1 for value in values_list if value >= 1)
            wins_2 = sum(1 for value in values_list if value >= 2)
            if wins_1 == 5:
                lines.append(
                    PlayerPropLine(
                        player_name=player_name,
                        team_name=team_name,
                        stat_key=stat_key,
                        threshold=1,
                        values=values_list,
                        wins=wins_1,
                        total=5,
                    ),
                )
            if wins_2 >= 4:
                lines.append(
                    PlayerPropLine(
                        player_name=player_name,
                        team_name=team_name,
                        stat_key=stat_key,
                        threshold=2,
                        values=values_list,
                        wins=wins_2,
                        total=5,
                    ),
                )
    return lines


def collect_player_props_for_day(day) -> List[PlayerPropLine]:
    fixtures = data_fetcher.get_fixtures_for_day(day)
    if len(fixtures) < 3:
        return []
    team_ids = {fixture.home_team_id for fixture in fixtures} | {
        fixture.away_team_id for fixture in fixtures
    }
    lines: List[PlayerPropLine] = []
    for team_id in sorted(team_ids):
        lines.extend(_collect_team_lines(team_id))
    return lines


def split_props_by_tier(
    lines: Iterable[PlayerPropLine],
) -> tuple[Dict[str, List[PlayerPropLine]], Dict[str, List[PlayerPropLine]]]:
    hundred: Dict[str, List[PlayerPropLine]] = {key: [] for key in STAT_TYPE_MAP}
    eighty: Dict[str, List[PlayerPropLine]] = {key: [] for key in STAT_TYPE_MAP}
    for line in lines:
        if line.threshold == 1 and line.wins == 5:
            hundred[line.stat_key].append(line)
        elif line.threshold == 2 and line.wins >= 4:
            eighty[line.stat_key].append(line)
    return hundred, eighty
