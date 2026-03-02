from __future__ import annotations

from datetime import date

def build_post_key(slot: str, scheduled_for: date) -> str:
    return f"{scheduled_for.isoformat()}_{slot}"
