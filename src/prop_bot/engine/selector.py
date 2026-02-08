from __future__ import annotations

from typing import Dict, List


def select_top_picks(candidates: List[Dict], count: int) -> List[Dict]:
    ranked = sorted(
        candidates,
        key=lambda item: (item["composite_score"], item["edge"]["edge_percentage"]),
        reverse=True,
    )
    return ranked[:count]
