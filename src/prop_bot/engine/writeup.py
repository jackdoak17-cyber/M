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
    stat_type_label = pick.get("stat_type_label", "")
    is_fouls_committed = stat_type_label == "fouls_committed" or "fouls committed" in market_label
    is_fouls_drawn = stat_type_label == "fouls_drawn" or "fouls drawn" in market_label
    is_fouls_market = is_fouls_committed or is_fouls_drawn
    is_shots_market = stat_type_label in {"shots", "shots_on_target"}
    is_home = bool(pick.get("is_home"))
    venue_avg = pick["baseline"].get("home_avg") if is_home else pick["baseline"].get("away_avg")
    other_avg = pick["baseline"].get("away_avg") if is_home else pick["baseline"].get("home_avg")
    opponent_label = "Opponent avg conceded"
    if is_fouls_committed:
        opponent_label = "Opponent fouls drawn per game"
    elif is_fouls_drawn:
        opponent_label = "Opponent fouls committed per game"

    opponent_stats = pick.get("opponent", {})
    rank_fewest = opponent_stats.get("rank_fewest_conceded")
    opponent_avg = opponent_stats.get("avg_conceded")
    league_avg = opponent_stats.get("league_avg")
    rank_most = opponent_stats.get("rank_most_conceded")
    total_teams = opponent_stats.get("total_teams")
    include_opponent_stats = (
        opponent_avg is not None
        and (is_fouls_market or rank_fewest != 1)
    )
    opponent_stats_line = ""
    if include_opponent_stats:
        parts = [f"{opponent_label}: {float(opponent_avg):.1f} per game"]
        if league_avg is not None:
            parts.append(f"league avg {float(league_avg):.1f}")
        if rank_most is not None and total_teams:
            parts.append(f"rank most {int(rank_most)}/{int(total_teams)}")
        opponent_stats_line = " (" + ", ".join(parts[1:]) + ")"
        opponent_stats_line = f"{parts[0]}{opponent_stats_line}" if len(parts) > 1 else parts[0]

    vs_similar = pick.get("vs_similar", {})
    vs_hit_rate = vs_similar.get("hitrate_vs_similar")
    vs_games = vs_similar.get("games_vs_similar")
    if vs_hit_rate is None:
        vs_hit_rate = 0.0
    if vs_games is None:
        vs_games = 0
    vs_examples = vs_similar.get("similar_teams_examples", []) or []
    include_vs_similar = is_shots_market and (vs_games or 0) > 0 and vs_hit_rate >= 60
    if not include_vs_similar:
        vs_examples = []
    vs_examples_text = ", ".join(vs_examples) if vs_examples else ""

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
        "stat_type_label": stat_type_label,
        "is_fouls_market": is_fouls_market,
        "opponent_stats_line": opponent_stats_line,
        "opponent_stats_required": is_fouls_market and bool(opponent_stats_line),
        "vs_similar": vs_similar,
        "vs_similar_hit_rate": vs_hit_rate,
        "vs_similar_games": vs_games,
        "vs_similar_examples": vs_examples,
        "vs_similar_examples_text": vs_examples_text,
        "include_vs_similar": include_vs_similar,
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
        "- Always mention the player's team (club) in the title or first sentence.\n"
        "- For fouls committed picks: reference how many fouls the opponent DRAWS, not commits.\n"
        "- For fouls drawn picks: reference how many fouls the opponent COMMITS, not draws.\n"
        "- For fouls markets, always include the opponent foul context line when provided (avg, league avg, rank).\n"
        "- Do NOT include vs_similar for fouls markets; it's only relevant for shots and SOT.\n"
        "- NEVER mention projection numbers, edge percentages, or model outputs.\n"
        "- Hit rates ALWAYS include the denominator: \"14 of his last 20\" not \"14 of his matches\".\n"
        "- Use the opponent name provided; never write \"opponent\" generically.\n"
        "- When vs_similar data includes team names, name them: \"against teams like X, Y, and Z\".\n"
        "- If vs_similar hit rate is below 60%, DO NOT mention it at all.\n"
        "- If the opponent ranks 1st for fewest conceded in the stat, do not frame it as a positive. "
        "Either mention it honestly as a factor to consider or leave it out.\n"
        "- Every sentence must include a number; no vague opinions like \"should create opportunities\".\n"
        "- Avoid filler like \"well above the line\"; let the numbers speak.\n"
        "- Do NOT include any stat that argues against the pick. Lead with the reasons it's value.\n"
        "- Always include the bookmaker and odds at the end.\n\n"
        "EXAMPLE OF A GOOD POST:\n\n"
        "🎯 Mancini (Roma) 2+ Fouls Committed vs Cagliari (Serie A)\n\n"
        "He's averaging 2.72 fouls per 90 this season and has committed 2+ in all 5 of his last 5 and 17 of his last 20 overall. "
        "Cagliari draw 15.0 fouls per game — most in Serie A vs the 12.4 league average. Looks good value to me.\n\n"
        "📊 17/20 (85%)\n"
        "💰 Kambi 1.84"
    )
    lines = [
        f"Player: {context['player']} ({context['team']}) vs {context['opponent_name']} ({context['league']})",
        f"Market: {context['market']}",
        f"Baseline per90: {context['baseline']['weighted_per90']:.2f}",
        f"Last 5 avg: {context['baseline']['last_5_avg']:.2f}",
        f"Venue: {context['venue']}",
        f"Venue avg: {context['venue_avg']:.2f}",
        f"Other venue avg: {context['other_venue_avg']:.2f}",
        f"Hit rate last 5: {context['hit_rates']['last_5']}",
        f"Hit rate last 20: {context['hit_rates']['last_20']}",
    ]
    if context["opponent_stats_line"]:
        prefix = "Opponent context (must use): " if context.get("opponent_stats_required") else ""
        lines.append(f"{prefix}{context['opponent_stats_line']}")
    if context.get("include_vs_similar"):
        lines.append(
            f"Similar hit rate: {context.get('vs_similar_hit_rate')}% over {context.get('vs_similar_games')} games"
        )
        lines.append(f"Similar opponents examples: {context.get('vs_similar_examples_text')}")
    lines.extend(
        [
            f"Opponent name (must be used exactly): {context['opponent_name']}",
            f"Bookmaker: {context.get('bookmaker')}",
            f"Book odds: {context.get('odds')}",
            "Write the note.",
        ]
    )
    user_prompt = "\n".join(lines)

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
    title_line = f"🎯 {context['player']} ({context['team']}) {context['market']} vs {opponent_name} ({league_name})"
    summary_rate, summary_pct = _summary_rate(context.get("raw_values", []), context["threshold"])
    summary_line = f"📊 {summary_rate} ({summary_pct}%)"
    odds_line = f"💰 {context.get('bookmaker')} {context.get('odds')}"

    if "vs Opponent" in text or "vs opponent" in text:
        text = text.replace("vs Opponent", f"vs {opponent_name}")
        text = text.replace("vs opponent", f"vs {opponent_name}")

    lines = [line for line in text.splitlines() if line.strip() != ""]
    if not lines:
        lines = [title_line]
    if not lines[0].startswith("🎯"):
        lines = [title_line, ""] + lines
    else:
        lines[0] = title_line
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
