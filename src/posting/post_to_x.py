from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone

from .content_resolver import SLOTS, resolve_content, resolve_target_date
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
    post_key = f"{target.isoformat()}_{slot}"
    approval = fetch_post_approval(post_key)
    if not approval or approval.status != "approved":
        print(f"Post not approved for {post_key}")
        return 0
    if approval.posted_at:
        print(f"Post already sent for {post_key}")
        return 0

    approved_content = (approval.content or "").strip()
    if not approved_content:
        print(f"Approved content is empty for {post_key}")
        return 1

    latest = resolve_content(slot, target)
    approved_hash = approval.content_hash or _content_hash(approved_content)
    latest_hash = _content_hash(latest.content) if latest else None
    if latest_hash and approved_hash != latest_hash:
        print(f"Detected content drift for {post_key}; posting approved snapshot.")

    preview = _truncate_text(approved_content)
    if dry_run:
        message = (
            f"DRY RUN — NOT posted to X\n"
            f"Slot: {slot}\nDate: {target.isoformat()} ({target.strftime('%A')})\n\n"
            f"{preview}"
        )
        send_message(message)
        return 0

    result = post_thread(approved_content)
    update_post_status(
        post_key,
        "approved",
        {
            "posted_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
            "posted_tweet_id": result.tweet_ids[0] if result.tweet_ids else None,
        },
    )
    label = SLOTS.get(slot, {}).get("label", slot)
    message = (
        f"Posted to X: {label}\n"
        f"Date: {target.isoformat()} ({target.strftime('%A')})\n"
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
