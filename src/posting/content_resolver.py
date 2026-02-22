from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .settings import get_posting_settings


@dataclass(frozen=True)
class ContentInfo:
    slot: str
    scheduled_for: date
    day_label: str
    path: Path
    content: str
    label: str
    combined: bool


OUTPUT_DIR = Path("output")
BY_FIXTURE_DIR = OUTPUT_DIR / "by_fixture"
PLAYER_PROPS_DIR = OUTPUT_DIR / "player_props"


SLOTS = {
    "weekend_fixture": {
        "label": "Weekend fixture props",
        "type": "fixture",
        "weekend": True,
    },
    "weekend_player_100": {
        "label": "Weekend player props (100% or combined)",
        "type": "player_100",
        "weekend": True,
    },
    "weekend_player_80": {
        "label": "Weekend player props (80%)",
        "type": "player_80",
        "weekend": True,
    },
    "weekday_fixture": {
        "label": "Weekday fixture props",
        "type": "fixture",
        "weekend": False,
    },
    "weekday_player": {
        "label": "Weekday player props",
        "type": "player_weekday",
        "weekend": False,
    },
}


def _day_label(target: date) -> str:
    return target.strftime("%A")


def _date_label(target: date) -> str:
    return target.strftime("%Y-%m-%d")


def resolve_target_date(mode: str) -> date:
    settings = get_posting_settings()
    tz = ZoneInfo(settings.timezone)
    today = datetime.now(tz).date()
    if mode == "preview":
        return today + timedelta(days=1)
    return today


def resolve_content(slot: str, target: date) -> ContentInfo | None:
    slot_config = SLOTS.get(slot)
    if not slot_config:
        raise ValueError(f"Unknown slot: {slot}")

    is_weekend = target.weekday() >= 5
    if slot_config["weekend"] is True and not is_weekend:
        return None
    if slot_config["weekend"] is False and is_weekend:
        return None

    day_label = _day_label(target)
    date_label = _date_label(target)
    day_key = day_label.lower()

    combined_path = PLAYER_PROPS_DIR / f"{date_label}_{day_key}_player_props.txt"
    fixture_path = BY_FIXTURE_DIR / f"{date_label}_{day_key}_prop_sheet_by_fixture.txt"
    props_100_path = PLAYER_PROPS_DIR / f"{date_label}_{day_key}_player_props_100.txt"
    props_80_path = PLAYER_PROPS_DIR / f"{date_label}_{day_key}_player_props_80.txt"

    content_path: Path | None = None
    combined = False

    content_type = slot_config["type"]
    if content_type == "fixture":
        content_path = fixture_path
    elif content_type == "player_100":
        if combined_path.exists():
            content_path = combined_path
            combined = True
        else:
            content_path = props_100_path
    elif content_type == "player_80":
        if combined_path.exists():
            return None
        content_path = props_80_path
    elif content_type == "player_weekday":
        if combined_path.exists():
            content_path = combined_path
            combined = True
        elif props_100_path.exists():
            content_path = props_100_path
        else:
            content_path = props_80_path

    if not content_path or not content_path.exists():
        return None

    content = content_path.read_text(encoding="utf-8").strip()
    if not content:
        return None

    label = slot_config["label"]
    if combined:
        label = f"{label} (combined)"

    return ContentInfo(
        slot=slot,
        scheduled_for=target,
        day_label=day_label,
        path=content_path,
        content=content,
        label=label,
        combined=combined,
    )
