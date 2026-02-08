from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List

from src.prop_bot.config import LEAGUES, MARKETS, get_settings
from src.prop_bot.engine import (
    adjustments,
    baseline,
    confidence,
    distribution,
    edge,
    fixtures,
    odds,
    opponent,
    output,
    players,
    selector,
    share,
    similar,
    writeup,
)
from src.prop_bot.engine.telegram_notify import send_telegram


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger(__name__)


def _passes_hit_rate_filter(raw_values: List[float], threshold: int) -> bool:
    values = [float(v) for v in raw_values if v is not None]
    n = len(values)
    if n < 5:
        return False
    if sum(1 for v in values[:5] if v >= threshold) < 4:
        return False
    if n >= 7 and sum(1 for v in values[:7] if v >= threshold) < 6:
        return False
    if n >= 10 and sum(1 for v in values[:10] if v >= threshold) < 7:
        return False
    if n > 10:
        hits_all = sum(1 for v in values if v >= threshold)
        if hits_all / n < 0.70:
            return False
    return True


def _build_candidate(
    fixture,
    player,
    market,
    threshold,
    baseline_data: Dict,
    opp_profile: Dict,
    league_avg: float,
    opp_rank: Dict,
    share_data: Dict | None,
    win_prob: float,
) -> Dict | None:
    venue_aligned = (
        baseline_data["home_avg"] >= baseline_data["away_avg"]
        if fixture.home_team_id == player.team_id
        else baseline_data["away_avg"] >= baseline_data["home_avg"]
    )
    context = {
        "opponent_avg_conceded": opp_profile.get("avg_conceded", 0.0),
        "opponent_sample_size": opp_profile.get("sample_size", 0),
        "opponent_rank": opp_rank.get("rank"),
        "league_avg": league_avg,
        "is_home": fixture.home_team_id == player.team_id,
        "team_win_probability": win_prob,
        "stat_type": market.label,
        "threshold": threshold,
        "share_projection": (share_data.get("player_share") * opp_profile.get("avg_conceded", 0.0))
        if share_data
        else None,
        "venue_rate_aligned": venue_aligned,
        "style_multiplier": 1.0,
    }

    projection = adjustments.calculate_adjusted_projection(baseline_data, context)
    conf = confidence.calculate_confidence(baseline_data, context)

    if conf["score"] < get_settings().min_confidence:
        return None

    dist = distribution.fit_player_distribution(
        baseline_data["raw_values"],
        projection["adjusted_projection"],
    )
    prob_key = f"{threshold}+"
    probability = dist["probabilities"].get(prob_key)
    if probability is None:
        return None

    odds_data = odds.get_player_market_odds(
        fixture.fixture_id,
        player.player_id,
        market.odds_market_key,
        threshold,
    )
    if not odds_data:
        return None
    price = odds_data["price"]
    if not (1.8 <= price <= 4.0):
        return None

    edge_data = edge.calculate_value_edge(probability, price)
    if edge_data["edge_percentage"] < get_settings().min_edge_pct:
        return None

    market_label = f"{threshold}+ {market.label.replace('_', ' ')}"
    opponent_name = fixture.away_team if fixture.home_team_id == player.team_id else fixture.home_team
    return {
        "player_id": player.player_id,
        "player_name": player.player_name,
        "team_id": player.team_id,
        "team_name": player.team_name,
        "opponent_id": fixture.away_team_id if fixture.home_team_id == player.team_id else fixture.home_team_id,
        "opponent_name": opponent_name,
        "fixture_id": fixture.fixture_id,
        "fixture_date": fixture.starting_at,
        "league_id": fixture.league_id,
        "league_name": fixture.league_name,
        "is_home": fixture.home_team_id == player.team_id,
        "stat_type_id": market.stat_type_id,
        "stat_type_label": market.label,
        "market_label": market_label,
        "threshold": threshold,
        "baseline": baseline_data,
        "opponent": {
            "avg_conceded": opp_profile.get("avg_conceded"),
            "league_avg": league_avg,
            "rank": opp_rank.get("rank"),
            "total_teams": opp_rank.get("total_teams"),
        },
        "vs_similar": {},
        "projection": projection,
        "confidence": conf,
        "probability": probability,
        "edge": edge_data,
        "odds": price,
        "bookmaker": odds_data.get("bookmaker"),
        "bookmaker_id": odds_data.get("bookmaker_id"),
    }


def run() -> None:
    settings = get_settings()
    log.info("=== PROP ENGINE RUN %s ===", datetime.utcnow().isoformat())

    if not settings.supabase_db_url:
        raise SystemExit("SUPABASE_DB_URL is required")

    upcoming_fixtures = fixtures.get_upcoming_fixtures()
    if not upcoming_fixtures:
        log.info("No upcoming fixtures in the next %s hours.", settings.lookahead_hours)
        send_telegram("No fixtures found for the next 48 hours.")
        return

    log.info("Found %s fixtures across %s leagues", len(upcoming_fixtures), len(LEAGUES))
    candidates: List[Dict] = []

    for fixture in upcoming_fixtures:
        opponent_context_cache: Dict[tuple[int, int, int], Dict] = {}
        team_win_odds_cache: Dict[int, float | None] = {}
        log.info(
            "Fixture %s vs %s (%s)",
            fixture.home_team,
            fixture.away_team,
            fixture.league_name,
        )
        eligible_players = players.get_eligible_players(fixture)
        log.info("  %s eligible players", len(eligible_players))

        for player in eligible_players:
            is_home = fixture.home_team_id == player.team_id
            opponent_id = fixture.away_team_id if is_home else fixture.home_team_id

            if player.team_id not in team_win_odds_cache:
                team_win_odds_cache[player.team_id] = odds.get_team_win_odds(
                    fixture.fixture_id,
                    player.team_id,
                    is_home,
                )
            win_odds = team_win_odds_cache[player.team_id]
            win_prob = 1 / win_odds if win_odds else 0.0

            for market in MARKETS:
                base = baseline.calculate_player_baseline(player.player_id, market.stat_type_id, fixture.league_id)
                if not base or base["sample_size"] < settings.min_appearances:
                    continue
                eligible_thresholds = []
                for threshold in market.thresholds:
                    if base["simple_avg"] < threshold * 0.5:
                        continue
                    if not _passes_hit_rate_filter(base["raw_values"], threshold):
                        continue
                    eligible_thresholds.append(threshold)
                if not eligible_thresholds:
                    continue

                opp_key = (opponent_id, market.stat_type_id, fixture.league_id)
                if opp_key not in opponent_context_cache:
                    opp_profile = opponent.get_opponent_profile(opponent_id, market.stat_type_id, fixture.league_id)
                    if not opp_profile:
                        opponent_context_cache[opp_key] = {"opp_profile": None}
                    else:
                        opponent_context_cache[opp_key] = {
                            "opp_profile": opp_profile,
                            "league_avg": opponent.get_league_average(market.stat_type_id, fixture.league_id),
                            "opp_rank": opponent.get_opponent_rank(opponent_id, market.stat_type_id, fixture.league_id),
                        }
                cached_context = opponent_context_cache[opp_key]
                if not cached_context.get("opp_profile"):
                    continue
                opp_profile = cached_context["opp_profile"]
                league_avg = cached_context["league_avg"]
                opp_rank = cached_context["opp_rank"]

                share_data = share.get_player_team_share(
                    player.player_id,
                    player.team_id,
                    market.stat_type_id,
                    fixture.league_id,
                )

                for threshold in eligible_thresholds:
                    candidate = _build_candidate(
                        fixture,
                        player,
                        market,
                        threshold,
                        base,
                        opp_profile,
                        league_avg,
                        opp_rank,
                        share_data,
                        win_prob,
                    )
                    if candidate:
                        candidate["composite_score"] = round(
                            (candidate["confidence"]["score"] * 0.3)
                            + (candidate["edge"]["our_probability"] * 100 * 0.5)
                            + (candidate["edge"]["edge_percentage"] * 0.2),
                            2,
                        )
                        candidates.append(candidate)

    log.info("Generated %s candidates after filters", len(candidates))
    top_picks = selector.select_top_picks(candidates, settings.max_candidates)

    if not top_picks:
        log.info("No qualifying picks today.")
        send_telegram("No qualifying picks today.")
        return

    if settings.include_similar:
        for pick in top_picks:
            pick["vs_similar"] = similar.get_performance_vs_similar(
                pick["player_id"],
                pick["team_id"],
                pick["opponent_id"],
                pick["stat_type_id"],
                pick["threshold"],
                pick["league_id"],
            )

    for idx, pick in enumerate(top_picks, start=1):
        pick["rank"] = idx
        context = writeup.build_writeup_context(pick)
        pick["writeup"] = writeup.generate_writeup(context)
        pick["result"] = {"actual_value": None, "hit": None, "checked_at": None}

    output_path = output.save_picks_to_file(top_picks, output_dir="picks")
    all_picks = output.load_all_picks(output_dir="picks")
    output.update_summary(all_picks, output_dir="picks")
    log.info("Saved picks to %s", output_path)

    summary_lines = [f"#{pick['rank']} {pick['player_name']} {pick['market_label']} vs {pick['opponent_name']}" for pick in top_picks]
    send_telegram("Picks generated:\\n" + "\\n".join(summary_lines))


if __name__ == "__main__":
    run()
