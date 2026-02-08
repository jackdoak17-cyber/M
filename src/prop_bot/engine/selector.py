from __future__ import annotations

from typing import Dict, List


def select_top_picks(candidates: List[Dict], count: int) -> List[Dict]:
    ranked = sorted(
        candidates,
        key=lambda item: (item["composite_score"], item["edge"]["edge_percentage"]),
        reverse=True,
    )
    seen_players = set()
    picks: List[Dict] = []
    for item in ranked:
        player_id = item.get("player_id")
        if player_id in seen_players:
            continue
        seen_players.add(player_id)
        picks.append(item)
        if len(picks) >= count:
            break
    return picks
