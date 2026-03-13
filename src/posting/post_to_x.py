from __future__ import annotations

import argparse
import hashlib
from datetime import datetime, timezone

from .content_resolver import SLOTS, resolve_content, resolve_target_date
from .supabase_client import fetch_post_approval, update_post_status
from .telegram_client import send_message
from .x_client import post_thread, post_thread_chunks


TELEGRAM_MAX = 3500


def _truncate_text(text: str, limit: int = TELEGRAM_MAX) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n\n[...truncated]"

def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _trim_blank_edges(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _to_block_text(lines: list[str]) -> str:
    trimmed = _trim_blank_edges(lines)
    if not trimmed:
        return ""
    return "\n".join(trimmed)


def _is_fixture_heading(line: str) -> bool:
    value = line.strip()
    if not value:
        return False
    lower = value.lower()
    return " vs " in lower and " - " in value


def _is_stat_line(line: str) -> bool:
    return "(won in " in line.lower()


def _build_weekend_fixture_thread(content: str) -> list[str] | None:
    lines = content.splitlines()
    heading_indices = [idx for idx, line in enumerate(lines) if _is_fixture_heading(line)]
    if not heading_indices:
        return None

    intro_text = _to_block_text(lines[: heading_indices[0]])
    fixture_blocks: list[str] = []
    footer_text = ""

    for idx, start in enumerate(heading_indices):
        end = heading_indices[idx + 1] if idx + 1 < len(heading_indices) else len(lines)
        block_lines = _trim_blank_edges(lines[start:end])
        if not block_lines:
            continue

        if idx == len(heading_indices) - 1:
            stat_positions = [pos for pos, line in enumerate(block_lines) if _is_stat_line(line)]
            if stat_positions:
                last_stat_pos = stat_positions[-1]
                footer_text = _to_block_text(block_lines[last_stat_pos + 1 :])
                block_lines = _trim_blank_edges(block_lines[: last_stat_pos + 1])

        block_text = _to_block_text(block_lines)
        if block_text:
            fixture_blocks.append(block_text)

    if not fixture_blocks:
        return None

    # Desired shape:
    # - Tweet 1: intro + first fixture block
    # - Middle tweets: one fixture block each
    # - Final tweet: last fixture block + footer (if present)
    if intro_text:
        fixture_blocks[0] = f"{intro_text}\n\n{fixture_blocks[0]}"
    if footer_text:
        fixture_blocks[-1] = f"{fixture_blocks[-1]}\n\n{footer_text}"
    return fixture_blocks


def _use_fixture_thread_structure(slot: str) -> bool:
    slot_cfg = SLOTS.get(slot) or {}
    return str(slot_cfg.get("type") or "") == "fixture"


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

    thread_chunks = _build_weekend_fixture_thread(approved_content) if _use_fixture_thread_structure(slot) else None
    preview_source = "\n\n---\n\n".join(thread_chunks) if thread_chunks else approved_content
    preview = _truncate_text(preview_source)
    if dry_run:
        thread_line = f"\nThread tweets: {len(thread_chunks)}" if thread_chunks else ""
        message = (
            f"DRY RUN — NOT posted to X\n"
            f"Slot: {slot}\nDate: {target.isoformat()} ({target.strftime('%A')}){thread_line}\n\n"
            f"{preview}"
        )
        send_message(message)
        return 0

    if thread_chunks:
        result = post_thread_chunks(thread_chunks)
    else:
        if _use_fixture_thread_structure(slot):
            print(f"Could not split fixture blocks for {post_key}; posting as a single thread.")
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
