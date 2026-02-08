from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional


@dataclass(frozen=True)
class Fixture:
    fixture_id: int
    starting_at: datetime
    home_team_id: int
    away_team_id: int
    home_team: str
    away_team: str
    league_id: int
    league_name: str


@dataclass(frozen=True)
class EligiblePlayer:
    player_id: int
    player_name: str
    team_id: int
    team_name: str
    appearances: int


@dataclass(frozen=True)
class Pick:
    rank: int
    player_id: int
    player_name: str
    team_id: int
    team_name: str
    opponent_id: int
    opponent_name: str
    fixture_id: int
    fixture_date: datetime
    league_id: int
    league_name: str
    is_home: bool
    stat_type_id: int
    stat_type_label: str
    threshold: int
    market_label: str
    baseline: Dict
    opponent: Dict
    vs_similar: Dict
    projection: Dict
    confidence: Dict
    probability: float
    edge: Dict
    odds: Optional[float]
    writeup: str
