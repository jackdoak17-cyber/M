from __future__ import annotations

from typing import Dict

from anthropic import Anthropic

from src.prop_bot.config import get_settings


def _hit_rate(values: list[float], threshold: int, window: int) -> str:
    if not values:
        return "0/0"
    slice_values = values[: min(window, len(values))]
    hits = sum(1 for value in slice_values if value >= threshold)
    return f"{hits}/{len(slice_values)}"


def _summary_rate(values: list[float], threshold: int) -> tuple[str, int]:
    if not values:
        return "0/0", 0
    if len(values) >= 20:
        window = 20
    elif len(values) >= 10:
        window = 10
    elif len(values) >= 7:
        window = 7
    else:
        window = 5
    slice_values = values[:window]
    hits = sum(1 for value in slice_values if value >= threshold)
    pct = int(round(hits / window * 100))
    return f"{hits}/{window}", pct


def build_writeup_context(pick: Dict) -> Dict:
    raw_values = [float(v) for v in pick["baseline"].get("raw_values", []) if v is not None]
    threshold = pick["threshold"]
    market_label = pick["market_label"].lower()
    is_home = bool(pick.get("is_home"))
    venue_avg = pick["baseline"].get("home_avg") if is_home else pick["baseline"].get("away_avg")
    other_avg = pick["baseline"].get("away_avg") if is_home else pick["baseline"].get("home_avg")
    opponent_label = "Opponent avg conceded"
    if "fouls committed" in market_label:
        opponent_label = "Opponent fouls drawn per game"
    elif "fouls drawn" in market_label:
        opponent_label = "Opponent fouls committed per game"

    opponent_stats = pick.get("opponent", {})
    rank_fewest = opponent_stats.get("rank_fewest_conceded")
    include_opponent_stats = rank_fewest != 1 and opponent_stats.get("avg_conceded") is not None
    opponent_stats_line = (
        f"{opponent_label}: {opponent_stats.get('avg_conceded')}" if include_opponent_stats else ""
    )
    opponent_rank_line = (
        f"Opponent rank (most conceded): {opponent_stats.get('rank_most_conceded')} of {opponent_stats.get('total_teams')}"
        if include_opponent_stats
        else ""
    )

    vs_similar = pick.get("vs_similar", {})
    vs_hit_rate = vs_similar.get("hitrate_vs_similar")
    vs_games = vs_similar.get("games_vs_similar")
    if vs_hit_rate is None:
        vs_hit_rate = 0.0
    if vs_games is None:
        vs_games = 0
    vs_examples = vs_similar.get("similar_teams_examples", []) or []
    if (vs_games or 0) == 0 or vs_hit_rate < 60:
        vs_examples = []
    vs_examples_text = ", ".join(vs_examples) if vs_examples else "none"

    return {
        "player": pick["player_name"],
        "team": pick["team_name"],
        "opponent_name": pick["opponent_name"],
        "league": pick["league_name"],
        "market": pick["market_label"],
        "threshold": threshold,
        "sample_size": len(raw_values),
        "raw_values": raw_values,
        "venue": "home" if is_home else "away",
        "venue_avg": venue_avg,
        "other_venue_avg": other_avg,
        "hit_rates": {
            "last_5": _hit_rate(raw_values, threshold, 5),
            "last_20": _hit_rate(raw_values, threshold, 20),
        },
        "baseline": {
            "weighted_per90": pick["baseline"].get("weighted_per90"),
            "simple_avg": pick["baseline"].get("simple_avg"),
            "last_5_avg": pick["baseline"].get("last_5_avg"),
            "home_avg": pick["baseline"].get("home_avg"),
            "away_avg": pick["baseline"].get("away_avg"),
        },
        "opponent_stats_line": opponent_stats_line,
        "opponent_rank_line": opponent_rank_line,
        "vs_similar": vs_similar,
        "vs_similar_hit_rate": vs_hit_rate,
        "vs_similar_games": vs_games,
        "vs_similar_examples": vs_examples,
        "vs_similar_examples_text": vs_examples_text,
        "odds": pick.get("odds"),
        "bookmaker": pick.get("bookmaker"),
    }


def generate_writeup(context: Dict) -> str:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return "Write-up unavailable (missing ANTHROPIC_API_KEY)."

    client = Anthropic(api_key=settings.anthropic_api_key)

    system_prompt = (
        "You are a betting analyst who writes short, factual, data-backed prop notes. "
        "Use the numbers provided. Write 3-5 sentences max.\n\n"
        "RULES:\n"
        "- For fouls committed picks: reference how many fouls the opponent DRAWS, not commits.\n"
        "- For fouls drawn picks: reference how many fouls the opponent COMMITS, not draws.\n"
        "- NEVER mention projection numbers, edge percentages, or model outputs.\n"
        "- Hit rates ALWAYS include the denominator: \"14 of his last 20\" not \"14 of his matches\".\n"
        "- Use the opponent name provided; never write \"opponent\" generically.\n"
        "- When vs_similar data includes team names, name them: \"against teams like X, Y, and Z\".\n"
        "- If vs_similar hit rate is below 60%, DO NOT mention it at all.\n"
        "- If the opponent ranks 1st for fewest conceded in the stat, do not frame it as a positive. "
        "Either mention it honestly as a factor to consider or leave it out.\n"
        "- Every sentence must include a number; no vague opinions like \"should create opportunities\".\n"
        "- Do NOT include any stat that argues against the pick. Lead with the reasons it's value.\n"
        "- Always include the bookmaker and odds at the end.\n\n"
        "EXAMPLE OF A GOOD POST:\n\n"
        "🎯 Avdullahu 1+ Foul Committed vs Bayern Munich (Bundesliga)\n\n"
        "He's averaging 1.27 fouls per 90 this season and has committed at least 1 foul in 5 of his last 5 and 14 of his last 20 overall. "
        "Away from home he averages 1.1 per game compared to 0.7 at home — and this is an away trip to Munich. "
        "Against similar opponents like Leverkusen, Gladbach, and Bayern this season he's hit this in 5 out of 6 games (83%). Looks good value to me.\n\n"
        "📊 14/20 (70%)\n"
        "💰 1.80"
    )
    user_prompt = (
        f"Player: {context['player']} ({context['team']}) vs {context['opponent_name']} "
        f"({context['league']})\n"
        f"Market: {context['market']}\n"
        f"Baseline per90: {context['baseline']['weighted_per90']:.2f}\n"
        f"Last 5 avg: {context['baseline']['last_5_avg']:.2f}\n"
        f"Venue: {context['venue']}\n"
        f"Venue avg: {context['venue_avg']:.2f}\n"
        f"Other venue avg: {context['other_venue_avg']:.2f}\n"
        f"Hit rate last 5: {context['hit_rates']['last_5']}\n"
        f"Hit rate last 20: {context['hit_rates']['last_20']}\n"
        f"{context['opponent_stats_line']}\n"
        f"{context['opponent_rank_line']}\n"
        f"Similar hit rate: {context.get('vs_similar_hit_rate')}% over {context.get('vs_similar_games')} games\n"
        f"Similar opponents examples: {context.get('vs_similar_examples_text')}\n"
        f"Opponent name (must be used exactly): {context['opponent_name']}\n"
        f"Bookmaker: {context.get('bookmaker')}\n"
        f"Book odds: {context.get('odds')}\n"
        "Write the note."
    )

    response = client.messages.create(
        model=settings.model_name,
        max_tokens=220,
        temperature=0.2,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    text = response.content[0].text.strip()
    opponent_name = context["opponent_name"]
    league_name = context["league"]
    title_line = f"🎯 {context['player']} {context['market']} vs {opponent_name} ({league_name})"
    summary_rate, summary_pct = _summary_rate(context.get("raw_values", []), context["threshold"])
    summary_line = f"📊 {summary_rate} ({summary_pct}%)"
    odds_line = f"💰 {context.get('bookmaker')} {context.get('odds')}"

    if "vs Opponent" in text or "vs opponent" in text:
        text = text.replace("vs Opponent", f"vs {opponent_name}")
        text = text.replace("vs opponent", f"vs {opponent_name}")

    lines = [line for line in text.splitlines() if line.strip() != ""]
    if not lines or not lines[0].startswith("🎯"):
        lines = [title_line, ""] + lines
    if not any(line.startswith("📊") for line in lines):
        lines.append("")
        lines.append(summary_line)
    if not any(line.startswith("💰") for line in lines):
        lines.append(odds_line)
    else:
        # Ensure odds line is last.
        odds_only = [line for line in lines if line.startswith("💰")]
        lines = [line for line in lines if not line.startswith("💰")] + odds_only

    return "\n".join(lines).strip()
