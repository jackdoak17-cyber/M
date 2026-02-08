from __future__ import annotations

from typing import Dict

from anthropic import Anthropic

from src.prop_bot.config import get_settings


def build_writeup_context(pick: Dict) -> Dict:
    return {
        "player": pick["player_name"],
        "team": pick["team_name"],
        "opponent": pick["opponent_name"],
        "league": pick["league_name"],
        "market": pick["market_label"],
        "baseline": pick["baseline"],
        "opponent": pick["opponent"],
        "vs_similar": pick.get("vs_similar", {}),
        "projection": pick["projection"],
        "confidence": pick["confidence"],
        "edge": pick["edge"],
        "odds": pick.get("odds"),
    }


def generate_writeup(context: Dict) -> str:
    settings = get_settings()
    if not settings.anthropic_api_key:
        return "Write-up unavailable (missing ANTHROPIC_API_KEY)."

    client = Anthropic(api_key=settings.anthropic_api_key)

    system_prompt = (
        "You are a betting analyst who writes short, factual, data-backed prop notes. "
        "No hype, no guarantees, no emojis. Use the numbers provided. "
        "Write 3-5 sentences max."
    )
    user_prompt = (
        f"Player: {context['player']} ({context['team']}) vs {context['opponent']} "
        f"({context['league']})\n"
        f"Market: {context['market']}\n"
        f"Baseline per90: {context['baseline']['weighted_per90']:.2f}\n"
        f"Last 5 avg: {context['baseline']['last_5_avg']:.2f}\n"
        f"Hit rates: {context['baseline']['hit_rates']}\n"
        f"Opponent avg conceded: {context['opponent'].get('avg_conceded')}\n"
        f"Opponent rank: {context['opponent'].get('rank')} of {context['opponent'].get('total_teams')}\n"
        f"Adjusted projection: {context['projection']['adjusted_projection']}\n"
        f"Our probability: {context['edge']['our_probability']}\n"
        f"Book odds: {context.get('odds')}\n"
        f"Edge %: {context['edge']['edge_percentage']}\n"
        "Write the note."
    )

    response = client.messages.create(
        model=settings.model_name,
        max_tokens=220,
        temperature=0.2,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return response.content[0].text.strip()
