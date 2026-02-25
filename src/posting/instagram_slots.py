from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

from .settings import get_posting_settings


@dataclass(frozen=True)
class InstagramSlotConfig:
    slot: str
    label: str
    post_type: str


INSTAGRAM_SLOTS: dict[str, InstagramSlotConfig] = {
    "ig_shot_props_value": InstagramSlotConfig(
        slot="ig_shot_props_value",
        label="Instagram Shot Props Potential Value",
        post_type="potential_value",
    ),
    "ig_shot_props_high_prob": InstagramSlotConfig(
        slot="ig_shot_props_high_prob",
        label="Instagram Shot Props High Probability",
        post_type="high_probability",
    ),
}


def get_instagram_slot(slot: str) -> InstagramSlotConfig:
    try:
        return INSTAGRAM_SLOTS[slot]
    except KeyError as exc:
        raise ValueError(f"Unknown Instagram slot: {slot}") from exc


def resolve_instagram_scheduled_date(override_date: str | None = None) -> date:
    if override_date:
        return date.fromisoformat(override_date)
    settings = get_posting_settings()
    tz = ZoneInfo(settings.timezone)
    return datetime.now(tz).date()


def build_post_key(slot: str, scheduled_for: date) -> str:
    return f"{scheduled_for.isoformat()}_{slot}"

