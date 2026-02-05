from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from config import get_settings
from src import data_fetcher


settings = get_settings()

TYPE_SHOTS_TOTAL = 42
TYPE_SHOTS_ON_TARGET = 86
TYPE_FOULS_COMMITTED = 56
TYPE_FOULS_DRAWN = 96

DEFENDER_ABBR = {"CB", "LB", "RB", "LWB", "RWB"}


@dataclass(frozen=True)
class PlayerWindow:
    fixture_ids: List[int]
    position_abbr: Optional[str]
    position_name: Optional[str]
    detailed_position_name: Optional[str]
    lineup_detailed_position_name: Optional[str]


@dataclass(frozen=True)
class StatHit:
    stat_key: str
    threshold: int
    wins: int
    total: int

    @property
    def rate(self) -> float:
        return self.wins / self.total if self.total else 0.0


def _is_defender(window: PlayerWindow) -> bool:
    abbr = (window.position_abbr or "").strip().upper()
    if abbr in DEFENDER_ABBR:
        return True
    candidates = [
        window.lineup_detailed_position_name,
        window.detailed_position_name,
        window.position_name,
    ]
    for label in candidates:
        if not label:
            continue
        normalized = label.lower()
        if "defender" in normalized or "back" in normalized:
            return True
    return False


def _build_player_window(player_id: int, team_id: int) -> Optional[PlayerWindow]:
    fixtures = data_fetcher.get_recent_team_fixtures(team_id, limit=20)
    if not fixtures:
        return None
    fixture_ids = [fixture.id for fixture in fixtures]
    player_rows = data_fetcher.get_fixture_players(fixture_ids, team_id)
    row_by_fixture: Dict[int, Dict] = {}
    for row in player_rows:
        if int(row["player_id"]) == player_id:
            row_by_fixture[int(row["fixture_id"])] = row

    last_fixture_id = fixture_ids[0]
    last_row = row_by_fixture.get(last_fixture_id)
    if not last_row or not last_row.get("is_starter"):
        return None

    started_fixtures: List[int] = []
    position_row: Optional[Dict] = None
    for fixture in fixtures:
        row = row_by_fixture.get(fixture.id)
        if row and row.get("is_starter"):
            started_fixtures.append(fixture.id)
            if position_row is None:
                position_row = row

    if len(started_fixtures) < 5:
        return None

    position_row = position_row or {}
    return PlayerWindow(
        fixture_ids=started_fixtures,
        position_abbr=position_row.get("position_abbr"),
        position_name=position_row.get("position_name"),
        detailed_position_name=position_row.get("detailed_position_name"),
        lineup_detailed_position_name=position_row.get("lineup_detailed_position_name"),
    )


def _load_stat_values(
    fixture_ids: Iterable[int],
    player_id: int,
    type_id: int,
) -> List[float]:
    fixtures = list(fixture_ids)
    rows = data_fetcher.get_fixture_player_stats(fixtures, [player_id], [type_id])
    values_by_fixture = {int(row["fixture_id"]): float(row["value"]) for row in rows}
    return [values_by_fixture.get(fixture_id, 0.0) for fixture_id in fixtures]


def _qualifying_hits(
    values: List[float],
    thresholds: Iterable[int],
    stat_key: str,
    min_rate: float = 0.75,
    min_games: int = 5,
) -> List[StatHit]:
    total = len(values)
    if total < min_games:
        return []
    hits: List[StatHit] = []
    for threshold in thresholds:
        wins = sum(1 for value in values if value >= threshold)
        if total and wins / total >= min_rate:
            hits.append(StatHit(stat_key=stat_key, threshold=threshold, wins=wins, total=total))
    return hits


def is_player_eligible(
    player_id: int,
    team_id: int,
    sidelined_ids: Optional[Iterable[int]] = None,
) -> bool:
    sidelined = set(sidelined_ids) if sidelined_ids is not None else set(
        data_fetcher.get_sidelined_player_ids(team_id),
    )
    if player_id in sidelined:
        return False
    window = _build_player_window(player_id, team_id)
    return window is not None


def get_qualifying_player_stats(
    player_id: int,
    team_id: int,
    sidelined_ids: Optional[Iterable[int]] = None,
) -> Dict[str, List[StatHit]]:
    sidelined = set(sidelined_ids) if sidelined_ids is not None else set(
        data_fetcher.get_sidelined_player_ids(team_id),
    )
    if player_id in sidelined:
        return {}
    window = _build_player_window(player_id, team_id)
    if not window:
        return {}

    is_defender = _is_defender(window)
    shots_thresholds = [1, 2, 3, 4] if is_defender else [2, 3, 4]
    sot_thresholds = [1, 2, 3]
    fouls_thresholds = [1, 2, 3, 4]

    shots_values = _load_stat_values(window.fixture_ids, player_id, TYPE_SHOTS_TOTAL)
    sot_values = _load_stat_values(window.fixture_ids, player_id, TYPE_SHOTS_ON_TARGET)
    fouls_committed_values = _load_stat_values(
        window.fixture_ids,
        player_id,
        TYPE_FOULS_COMMITTED,
    )
    fouls_won_values = _load_stat_values(window.fixture_ids, player_id, TYPE_FOULS_DRAWN)

    shots_hits = _qualifying_hits(shots_values, shots_thresholds, "shots")
    sot_hits = _qualifying_hits(sot_values, sot_thresholds, "shots_on_target")
    fouls_committed_hits = _qualifying_hits(
        fouls_committed_values,
        fouls_thresholds,
        "fouls_committed",
    )
    fouls_won_hits = _qualifying_hits(fouls_won_values, fouls_thresholds, "fouls_won")

    return {
        "shots": shots_hits,
        "shots_on_target": sot_hits,
        "fouls_committed": fouls_committed_hits,
        "fouls_won": fouls_won_hits,
    }
