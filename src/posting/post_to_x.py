from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone

from .content_resolver import resolve_content, resolve_target_date
from .supabase_client import fetch_post_approval, update_post_status
from .telegram_client import send_message
from .x_client import post_thread


TELEGRAM_MAX = 3500


def _truncate_text(text: str, limit: int = TELEGRAM_MAX) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n\n[...truncated]"

def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def run(slot: str, dry_run: bool) -> int:
    target = resolve_target_date("post", slot=slot)
    info = resolve_content(slot, target)
    if info is None:
        print(f"No content found for slot={slot} date={target}")
        return 0

    post_key = f"{info.scheduled_for.isoformat()}_{slot}"
    approval = fetch_post_approval(post_key)
    if not approval or approval.status != "approved":
        print(f"Post not approved for {post_key}")
        return 0
    current_hash = _content_hash(info.content)
    if not approval.content_hash or approval.content_hash != current_hash:
        update_post_status(
            post_key,
            "pending",
            {
                "content": info.content,
                "content_hash": current_hash,
                "content_path": str(info.path),
            },
        )
        send_message(
            "Approval reset because the fixture sheet changed after approval. "
            "Please review the new preview and approve again."
        )
        print(f"Approval reset for {post_key}: content changed")
        return 0
    if approval.posted_at:
        print(f"Post already sent for {post_key}")
        return 0

    preview = _truncate_text(info.content)
    if dry_run:
        message = (
            f"DRY RUN — NOT posted to X\n"
            f"Slot: {slot}\nDate: {info.scheduled_for.isoformat()} ({info.day_label})\n\n"
            f"{preview}"
        )
        send_message(message)
        return 0

    result = post_thread(info.content)
    update_post_status(
        post_key,
        "approved",
        {
            "posted_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "posted_tweet_id": result.tweet_ids[0] if result.tweet_ids else None,
        },
    )
    message = (
        f"Posted to X: {info.label}\n"
        f"Date: {info.scheduled_for.isoformat()} ({info.day_label})\n"
        f"Tweets: {', '.join(result.tweet_ids)}"
    )
    send_message(message)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Post approved content to X.")
    parser.add_argument("--slot", required=True)
    parser.add_argument("--dry-run", default="true")
    args = parser.parse_args()
    dry_run = str(args.dry_run).lower() in {"1", "true", "yes"}
    raise SystemExit(run(args.slot, dry_run))


if __name__ == "__main__":
    main()
