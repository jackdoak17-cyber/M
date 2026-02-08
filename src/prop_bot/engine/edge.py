from __future__ import annotations

from typing import Dict


def classify_edge(edge_pct: float) -> str:
    if edge_pct >= 15:
        return "PREMIUM"
    if edge_pct >= 10:
        return "STRONG"
    if edge_pct >= 5:
        return "MODERATE"
    if edge_pct >= 2:
        return "SLIGHT"
    return "NONE"


def calculate_value_edge(our_probability: float, bookmaker_odds: float) -> Dict:
    if bookmaker_odds <= 0:
        return {
            "our_probability": our_probability,
            "implied_probability": 0,
            "probability_edge": 0,
            "fair_odds": 0,
            "bookmaker_odds": bookmaker_odds,
            "expected_value": 0,
            "edge_percentage": 0,
            "kelly_quarter": 0,
            "rating": "NONE",
        }

    implied_prob = 1 / bookmaker_odds
    fair_odds = 1 / our_probability if our_probability > 0 else 0
    expected_value = (our_probability * bookmaker_odds) - 1
    edge_pct = expected_value * 100
    kelly_full = (our_probability * bookmaker_odds - 1) / (bookmaker_odds - 1)
    kelly_quarter = max(0, kelly_full * 0.25)

    return {
        "our_probability": round(our_probability, 4),
        "implied_probability": round(implied_prob, 4),
        "probability_edge": round(our_probability - implied_prob, 4),
        "fair_odds": round(fair_odds, 2),
        "bookmaker_odds": bookmaker_odds,
        "expected_value": round(expected_value, 4),
        "edge_percentage": round(edge_pct, 2),
        "kelly_quarter": round(kelly_quarter, 4),
        "rating": classify_edge(edge_pct),
    }
