from __future__ import annotations

from datetime import date

def approval_slot(slot: str) -> str:
    return f"instagram_{slot}"


def build_post_key(slot: str, scheduled_for: date) -> str:
    return f"{scheduled_for.isoformat()}_{approval_slot(slot)}"
