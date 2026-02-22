from __future__ import annotations

import argparse
from datetime import datetime, timezone

from .content_resolver import resolve_content, resolve_target_date
from .supabase_client import upsert_post_approval
from .telegram_client import send_message


TELEGRAM_MAX = 3500


def _truncate_text(text: str, limit: int = TELEGRAM_MAX) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n\n[...truncated]"


def run(slot: str) -> int:
    target = resolve_target_date("preview")
    info = resolve_content(slot, target)
    if info is None:
        print(f"No content found for slot={slot} date={target}")
        return 0

    post_key = f"{info.scheduled_for.isoformat()}_{slot}"
    post_date = info.scheduled_for.isoformat()
    payload = {
        "post_key": post_key,
        "slot": slot,
        "post_type": slot,
        "post_date": post_date,
        "scheduled_for": info.scheduled_for.isoformat(),
        "status": "pending",
        "content_path": str(info.path),
        "content": info.content,
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
    args = parser.parse_args()
    raise SystemExit(run(args.slot))


if __name__ == "__main__":
    main()
