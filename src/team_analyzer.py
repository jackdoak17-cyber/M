from __future__ import annotations

from dataclasses import dataclass
from math import floor
from typing import Dict, Iterable, List

from src import data_fetcher


TYPE_SHOTS_TOTAL = 42
TYPE_SHOTS_ON_TARGET = 86

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
    line: float
    line_minus_two: float

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
    min_rate: float = 0.8,
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
        wins = sum(
            1
            for fixture_id in fixture_ids
            if values_by_fixture.get(fixture_id, 0.0) >= line_minus_two
        )
        if wins / total >= min_rate:
            threshold = max(0, floor(line_minus_two))
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

    return hits
