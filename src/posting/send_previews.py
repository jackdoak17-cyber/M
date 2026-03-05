from __future__ import annotations

import argparse
import hashlib
from datetime import date, datetime, timezone
from pathlib import Path

from .content_resolver import SLOTS, resolve_content, resolve_target_date
from .supabase_client import upsert_post_approval
from .telegram_client import send_message


TELEGRAM_MAX = 3500


def _split_text(text: str, limit: int = TELEGRAM_MAX) -> list[str]:
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    remaining = text
    while len(remaining) > limit:
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0 or split_at < limit // 2:
            split_at = limit
        part = remaining[:split_at].rstrip()
        if part:
            parts.append(part)
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        parts.append(remaining)
    return parts


def _build_preview_messages(header: str, content: str, limit: int = TELEGRAM_MAX) -> list[str]:
    # Reserve room for the header in the first Telegram message.
    first_body_limit = max(1, limit - len(header))
    if limit >= 200:
        first_body_limit = max(200, first_body_limit)
    first_body_limit = min(first_body_limit, limit)
    body_parts = _split_text(content, first_body_limit)
    if not body_parts:
        return [header.rstrip()]

    messages = [header + body_parts[0]]
    for part in body_parts[1:]:
        messages.append(part)
    return messages

def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _requires_prop_regeneration(slot: str) -> bool:
    slot_cfg = SLOTS.get(slot) or {}
    slot_type = str(slot_cfg.get("type") or "")
    return slot_type in {"fixture", "player_100", "player_80", "player_weekday"}


def _clear_prop_outputs_for_day(target: date) -> None:
    date_label = target.isoformat()
    day_key = target.strftime("%A").lower()
    paths = [
        Path("output") / "by_fixture" / f"{date_label}_{day_key}_prop_sheet_by_fixture.txt",
        Path("output") / "player_props" / f"{date_label}_{day_key}_player_props.txt",
        Path("output") / "player_props" / f"{date_label}_{day_key}_player_props_100.txt",
        Path("output") / "player_props" / f"{date_label}_{day_key}_player_props_80.txt",
    ]
    for path in paths:
        if path.exists():
            path.unlink()


def _regenerate_prop_outputs_for_day(target: date) -> None:
    from src.main import main as generate_main

    _clear_prop_outputs_for_day(target)
    generate_main(
        [
            "--start-date",
            target.isoformat(),
            "--days",
            "1",
            "--output-dir",
            "output",
        ],
    )


def run(slot: str, target_date: str | None = None) -> int:
    if target_date:
        target = date.fromisoformat(target_date)
    else:
        target = resolve_target_date("preview", slot=slot)
    if _requires_prop_regeneration(slot):
        _regenerate_prop_outputs_for_day(target)
    info = resolve_content(slot, target)
    if info is None:
        print(f"No content found for slot={slot} date={target}")
        return 0

    post_key = f"{info.scheduled_for.isoformat()}_{slot}"
    post_date = info.scheduled_for.isoformat()
    content_hash = _content_hash(info.content)
    payload = {
        "post_key": post_key,
        "slot": slot,
        "post_type": slot,
        "post_date": post_date,
        "scheduled_for": info.scheduled_for.isoformat(),
        "status": "pending",
        "content_path": str(info.path),
        "content": info.content,
        "content_hash": content_hash,
        "updated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    upsert_post_approval(payload)

    header = (
        f"Preview: {info.label}\n"
        f"Date: {info.scheduled_for.isoformat()} ({info.day_label})\n"
        f"Key: {post_key}\n\n"
    )
    messages = _build_preview_messages(header, info.content)

    buttons = [
        [{"text": "✅ Approve", "callback_data": f"approve:{slot}:{post_date}"}],
        [{"text": "❌ Reject", "callback_data": f"reject:{slot}:{post_date}"}],
    ]
    if len(messages) == 1:
        send_message(messages[0], buttons=buttons)
    else:
        for text in messages[:-1]:
            send_message(text)
        send_message(messages[-1], buttons=buttons)
    print(f"Preview sent for {post_key} ({len(messages)} message(s))")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Send Telegram previews for scheduled posts.")
    parser.add_argument("--slot", required=True)
    parser.add_argument("--date", dest="target_date", help="Override target date (YYYY-MM-DD).")
    args = parser.parse_args()
    raise SystemExit(run(args.slot, args.target_date))


if __name__ == "__main__":
    main()
