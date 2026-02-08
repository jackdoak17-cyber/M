from __future__ import annotations

from typing import Dict


def calculate_confidence(baseline: Dict, context: Dict) -> Dict:
    score = 50

    n = baseline.get("sample_size", 0)
    if n >= 20:
        score += 15
    elif n >= 15:
        score += 10
    elif n >= 10:
        score += 5
    elif n < 8:
        score -= 10

    cv = baseline.get("coeff_of_variation", 0)
    if cv < 0.25:
        score += 15
    elif cv < 0.40:
        score += 8
    elif cv > 0.80:
        score -= 15

    trend = baseline.get("last_5_avg", 0) - baseline.get("simple_avg", 0)
    if trend > 0.5:
        score += 10
    elif trend > 0:
        score += 5
    elif trend < -0.5:
        score -= 10
    elif trend < 0:
        score -= 5

    sub_risk = 0
    if n:
        sub_risk = baseline.get("times_subbed_early", 0) / n
    if sub_risk == 0:
        score += 10
    elif sub_risk < 0.2:
        score += 5
    elif sub_risk > 0.4:
        score -= 10

    opp_n = context.get("opponent_sample_size", 0)
    if opp_n >= 10:
        score += 5
    elif opp_n < 5:
        score -= 5

    venue_aligned = context.get("venue_rate_aligned", False)
    if venue_aligned:
        score += 5
    else:
        score -= 3

    threshold = context.get("threshold")
    raw_values = baseline.get("raw_values", [])
    if threshold is not None and raw_values:
        window = raw_values[: min(10, len(raw_values))]
        hits = sum(1 for v in window if float(v) >= threshold)
        last_10_hitrate = hits / len(window)
        if last_10_hitrate == 0:
            score -= 40
        elif last_10_hitrate < 0.3:
            score -= 20

    score = max(0, min(100, score))
    tier = "PASS"
    if score >= 80:
        tier = "LOCK"
    elif score >= 65:
        tier = "STRONG"
    elif score >= 50:
        tier = "LEAN"
    elif score >= 35:
        tier = "SPECULATIVE"

    return {"score": score, "tier": tier}
