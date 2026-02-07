from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Dict, Iterable, List, Optional

from src import data_fetcher


TYPE_SHOTS_TOTAL = 42
TYPE_SHOTS_ON_TARGET = 86
TYPE_CORNERS = 34

MARKET_KEYS = {
    "shots": "team_shots",
    "shots_on_target": "team_shots_on_target",
}


@dataclass(frozen=True)
class TeamStatHit:
    stat_key: str
    threshold: int
    wins: int
    total: int
    line: Optional[float]
    line_minus_two: Optional[float]

    @property
    def rate(self) -> float:
        return self.wins / self.total if self.total else 0.0


def _load_team_stat_values(
    fixture_ids: Iterable[int],
    team_id: int,
    type_id: int,
) -> Dict[int, float]:
    fixtures = list(fixture_ids)
    rows = data_fetcher.get_fixture_team_stats(fixtures, team_id, [type_id])
    return {int(row["fixture_id"]): float(row["value"]) for row in rows}


def get_qualifying_team_stats(
    team_id: int,
    fixture_id: int,
    min_rate: float = 0.75,
    min_games: int = 5,
) -> List[TeamStatHit]:
    fixtures = data_fetcher.get_recent_team_fixtures(team_id, limit=20)
    if len(fixtures) < min_games:
        return []

    fixture_ids = [fixture.id for fixture in fixtures]
    total = len(fixture_ids)
    if total < min_games:
        return []

    shots_values = _load_team_stat_values(fixture_ids, team_id, TYPE_SHOTS_TOTAL)
    sot_values = _load_team_stat_values(fixture_ids, team_id, TYPE_SHOTS_ON_TARGET)
    corners_values = _load_team_stat_values(fixture_ids, team_id, TYPE_CORNERS)

    hits: List[TeamStatHit] = []
    for stat_key, values_by_fixture in (
        ("shots", shots_values),
        ("shots_on_target", sot_values),
    ):
        market_key = MARKET_KEYS[stat_key]
        line = data_fetcher.get_bet365_team_line(fixture_id, team_id, market_key)
        if line is None:
            continue
        line_minus_two = line - 2
        if line_minus_two < 1:
            # Skip meaningless thresholds like 0+.
            continue
        threshold = max(0, floor(line_minus_two))
        if stat_key == "shots" and threshold < 9:
            continue
        if stat_key == "shots_on_target" and threshold < 3:
            continue
        wins = sum(
            1
            for fixture_id in fixture_ids
            if values_by_fixture.get(fixture_id, 0.0) >= threshold
        )
        if wins / total >= min_rate:
            hits.append(
                TeamStatHit(
                    stat_key=stat_key,
                    threshold=threshold,
                    wins=wins,
                    total=total,
                    line=line,
                    line_minus_two=line_minus_two,
                ),
            )

    corner_series = [corners_values.get(fixture_id, 0.0) for fixture_id in fixture_ids]
    max_corners = max(corner_series) if corner_series else 0.0
    if max_corners >= 3:
        for threshold in range(3, int(floor(max_corners)) + 1):
            corners_wins = sum(1 for value in corner_series if value >= threshold)
            if corners_wins / total >= min_rate:
                hits.append(
                    TeamStatHit(
                        stat_key="corners",
                        threshold=threshold,
                        wins=corners_wins,
                        total=total,
                        line=None,
                        line_minus_two=None,
                    ),
                )

    return hits
