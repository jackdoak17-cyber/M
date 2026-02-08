from __future__ import annotations

from typing import Dict


def opponent_multiplier(opponent_avg: float, league_avg: float, sample_size: int) -> float:
    if league_avg <= 0 or opponent_avg <= 0:
        return 1.0
    raw = opponent_avg / league_avg
    regression = sample_size / (sample_size + 10)
    return 1.0 + (raw - 1.0) * regression


def venue_multiplier(simple_avg: float, home_avg: float, away_avg: float, home_games: int, away_games: int, is_home: bool) -> float:
    if simple_avg <= 0:
        return 1.0
    venue_rate = home_avg if is_home else away_avg
    if venue_rate <= 0:
        return 1.0
    venue_sample = home_games if is_home else away_games
    regression = venue_sample / (venue_sample + 5) if venue_sample else 0.0
    raw = venue_rate / simple_avg
    return 1.0 + (raw - 1.0) * regression


def minutes_multiplier(avg_minutes: float) -> float:
    if avg_minutes <= 0:
        return 1.0
    return min(avg_minutes / 90.0, 1.0)


def game_state_multiplier(win_probability: float, stat_type: str) -> float:
    if win_probability <= 0:
        return 1.0
    bands = {
        "shots": [
            (0.0, 0.30, 0.88),
            (0.30, 0.45, 0.95),
            (0.45, 0.55, 1.00),
            (0.55, 0.70, 1.05),
            (0.70, 0.85, 0.95),
            (0.85, 1.0, 0.85),
        ],
        "shots_on_target": [
            (0.0, 0.30, 0.90),
            (0.30, 0.45, 0.96),
            (0.45, 0.55, 1.00),
            (0.55, 0.70, 1.04),
            (0.70, 0.85, 0.96),
            (0.85, 1.0, 0.88),
        ],
        "fouls_committed": [
            (0.0, 0.30, 1.15),
            (0.30, 0.45, 1.08),
            (0.45, 0.55, 1.00),
            (0.55, 0.70, 0.95),
            (0.70, 0.85, 0.90),
            (0.85, 1.0, 0.82),
        ],
        "fouls_drawn": [
            (0.0, 0.30, 0.85),
            (0.30, 0.45, 0.92),
            (0.45, 0.55, 1.00),
            (0.55, 0.70, 1.08),
            (0.70, 0.85, 1.05),
            (0.85, 1.0, 0.90),
        ],
        "tackles": [
            (0.0, 0.30, 1.20),
            (0.30, 0.45, 1.10),
            (0.45, 0.55, 1.00),
            (0.55, 0.70, 0.92),
            (0.70, 0.85, 0.85),
            (0.85, 1.0, 0.75),
        ],
    }
    for low, high, mult in bands.get(stat_type, []):
        if low <= win_probability < high:
            return mult
    return 1.0


def calculate_adjusted_projection(baseline: Dict, context: Dict) -> Dict:
    adjustments: Dict[str, Dict] = {}

    opp_mult = opponent_multiplier(
        context.get("opponent_avg_conceded", 0.0),
        context.get("league_avg", 0.0),
        context.get("opponent_sample_size", 0),
    )
    adjustments["opponent"] = {
        "multiplier": opp_mult,
        "concedes": context.get("opponent_avg_conceded"),
        "league_avg": context.get("league_avg"),
        "rank": context.get("opponent_rank"),
    }

    venue_mult = venue_multiplier(
        baseline.get("simple_avg", 0.0),
        baseline.get("home_avg", 0.0),
        baseline.get("away_avg", 0.0),
        baseline.get("home_games", 0),
        baseline.get("away_games", 0),
        context.get("is_home", True),
    )
    adjustments["venue"] = {
        "multiplier": venue_mult,
        "venue_avg": baseline.get("home_avg") if context.get("is_home") else baseline.get("away_avg"),
        "overall_avg": baseline.get("simple_avg"),
        "is_home": context.get("is_home"),
    }

    mins_mult = minutes_multiplier(baseline.get("avg_minutes", 0.0))
    adjustments["minutes"] = {
        "multiplier": mins_mult,
        "avg_minutes": baseline.get("avg_minutes"),
        "times_subbed_early": baseline.get("times_subbed_early"),
        "sample_size": baseline.get("sample_size"),
    }

    gs_mult = game_state_multiplier(context.get("team_win_probability", 0.0), context.get("stat_type", ""))
    adjustments["game_state"] = {"multiplier": gs_mult}

    style_mult = context.get("style_multiplier", 1.0)
    adjustments["style"] = {"multiplier": style_mult}

    base_per90 = baseline.get("weighted_per90", 0.0)
    total_mult = 1.0
    for item in adjustments.values():
        total_mult *= item.get("multiplier", 1.0)

    share_projection = context.get("share_projection")
    if share_projection is None:
        share_projection = base_per90 * total_mult

    adjusted_per90 = (base_per90 * total_mult * 0.6) + (share_projection * 0.4)
    expected_minutes = baseline.get("avg_minutes", 90.0)
    expected_total = adjusted_per90 * (expected_minutes / 90.0)

    return {
        "baseline_per90": round(base_per90, 2),
        "adjusted_projection": round(expected_total, 2),
        "adjustments_applied": adjustments,
        "total_adjustment_factor": round(total_mult, 3),
    }
