from __future__ import annotations

import argparse
import hashlib
from datetime import date, datetime, timezone

from .content_resolver import resolve_content, resolve_target_date
from .supabase_client import upsert_post_approval
from .telegram_client import send_message


TELEGRAM_MAX = 3500


def _truncate_text(text: str, limit: int = TELEGRAM_MAX) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n\n[...truncated]"

def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(slot: str, target_date: str | None = None) -> int:
    if target_date:
        target = date.fromisoformat(target_date)
    else:
        target = resolve_target_date("preview", slot=slot)
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
    body = _truncate_text(info.content)
    text = header + body

    buttons = [
        [{"text": "✅ Approve", "callback_data": f"approve:{slot}:{post_date}"}],
        [{"text": "❌ Reject", "callback_data": f"reject:{slot}:{post_date}"}],
    ]
    send_message(text, buttons=buttons)
    print(f"Preview sent for {post_key}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Send Telegram previews for scheduled posts.")
    parser.add_argument("--slot", required=True)
    parser.add_argument("--date", dest="target_date", help="Override target date (YYYY-MM-DD).")
    args = parser.parse_args()
    raise SystemExit(run(args.slot, args.target_date))


if __name__ == "__main__":
    main()
