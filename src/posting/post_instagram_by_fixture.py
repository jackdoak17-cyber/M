from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any

from src.instagram.meta_graph import InstagramGraphClient, MetaGraphSettings
from src.instagram.r2_storage import R2Settings, R2Storage

from .content_resolver import resolve_target_date
from .instagram_slots import build_post_key
from .settings import get_posting_settings
from .supabase_client import fetch_post_approval, update_post_status
from .telegram_client import send_message


def _content_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _slot_label(slot: str) -> str:
    return {
        "weekend_fixture": "Instagram by-fixture weekend prototype",
        "weekday_fixture": "Instagram by-fixture weekday prototype",
    }.get(slot, f"Instagram by-fixture {slot}")


def _require_instagram_client() -> InstagramGraphClient:
    settings = get_posting_settings()
    missing = [
        name
        for name, value in [
            ("INSTAGRAM_ACCESS_TOKEN", settings.instagram_access_token),
            ("INSTAGRAM_ACCOUNT_ID", settings.instagram_account_id),
        ]
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required Instagram env vars: {', '.join(missing)}")
    return InstagramGraphClient(
        MetaGraphSettings(
            instagram_account_id=settings.instagram_account_id or "",
            access_token=settings.instagram_access_token or "",
        )
    )


def _r2_storage_or_none() -> R2Storage | None:
    settings = get_posting_settings()
    required = [
        settings.cloudflare_r2_access_key,
        settings.cloudflare_r2_secret_key,
        settings.cloudflare_r2_bucket_name,
        settings.cloudflare_r2_public_url,
        settings.s3_api_endpoint,
    ]
    if not all(required):
        return None
    return R2Storage(
        R2Settings(
            access_key_id=settings.cloudflare_r2_access_key or "",
            secret_access_key=settings.cloudflare_r2_secret_key or "",
            bucket_name=settings.cloudflare_r2_bucket_name or "",
            public_base_url=settings.cloudflare_r2_public_url or "",
            endpoint_url=settings.s3_api_endpoint or "",
        )
    )


def _parse_preview_payload(raw: str) -> dict[str, Any]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Approved Instagram payload is not valid JSON.") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Approved Instagram payload is not a JSON object.")
    return data


def _reset_approval_due_to_content_change(post_key: str, reason: str) -> None:
    update_post_status(
        post_key,
        "pending",
        {
            "content_hash": None,
            "updated_at": _utc_now_iso(),
        },
    )
    send_message(
        "Instagram by-fixture approval reset because the carousel content changed after approval.\n"
        f"Reason: {reason}\n"
        "Please send a fresh preview and approve again."
    )


def run(
    *,
    slot: str,
    target_date: str | None = None,
    dry_run: bool = False,
    skip_cleanup: bool = False,
) -> int:
    scheduled_for = date.fromisoformat(target_date) if target_date else resolve_target_date("post", slot=slot)
    scheduled_str = scheduled_for.isoformat()
    post_key = build_post_key(slot, scheduled_for)

    approval = fetch_post_approval(post_key)
    if not approval or approval.status != "approved":
        print(f"Post not approved for {post_key}")
        return 0
    if approval.posted_at:
        print(f"Instagram post already sent for {post_key}")
        return 0

    preview_payload = _parse_preview_payload(approval.content)
    if preview_payload.get("channel") != "instagram":
        print(f"Approval payload for {post_key} is not Instagram content")
        return 0

    approved_fingerprint = str(preview_payload.get("manifest_content_fingerprint") or "")
    if not approved_fingerprint:
        raise RuntimeError(f"Approval payload missing manifest_content_fingerprint for {post_key}")

    current_payload_hash = _content_hash(preview_payload)
    if approval.content_hash and approval.content_hash != current_payload_hash:
        _reset_approval_due_to_content_change(post_key, "approval payload hash mismatch")
        print(f"Approval reset for {post_key}: payload hash mismatch")
        return 0

    image_urls = list(preview_payload.get("image_urls") or [])
    caption = str(preview_payload.get("caption") or "")
    if len(image_urls) < 2:
        raise RuntimeError(f"Instagram payload for {post_key} has fewer than 2 images.")

    if dry_run:
        send_message(
            "DRY RUN — NOT posted to Instagram\n"
            f"Slot: {slot}\nDate: {scheduled_str}\n"
            f"Images: {len(image_urls)}\n"
            f"Caption length: {len(caption)}"
        )
        return 0

    client = _require_instagram_client()
    result = client.create_and_publish_carousel(image_urls, caption)
    permalink = None
    try:
        media_info = client.get_media(result.media_id, fields="id,permalink")
        permalink = media_info.get("permalink")
    except Exception as exc:  # noqa: BLE001
        send_message(f"Instagram by-fixture post published but failed to fetch permalink: {exc}")

    update_post_status(
        post_key,
        "approved",
        {
            "posted_at": _utc_now_iso(),
            "posted_tweet_id": result.media_id,
        },
    )

    cleanup_message = ""
    if not skip_cleanup:
        try:
            r2 = _r2_storage_or_none()
            keys = list(preview_payload.get("image_keys") or [])
            if r2 and keys:
                deleted_count = r2.delete_keys(keys)
                cleanup_message = f"\nR2 cleanup: deleted {deleted_count}/{len(keys)} objects"
        except Exception as exc:  # noqa: BLE001
            cleanup_message = f"\nR2 cleanup warning: {exc}"

    msg = [
        f"Posted to Instagram: {_slot_label(slot)}",
        f"Date: {scheduled_str}",
        f"Media ID: {result.media_id}",
    ]
    if permalink:
        msg.append(f"Link: {permalink}")
    if cleanup_message:
        msg.append(cleanup_message.strip())
    send_message("\n".join(msg))
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Post approved by-fixture Instagram carousel content.")
    parser.add_argument("--slot", required=True, choices=["weekend_fixture", "weekday_fixture"])
    parser.add_argument("--date", dest="target_date", help="Scheduled post date (YYYY-MM-DD).")
    parser.add_argument("--dry-run", default="true")
    parser.add_argument("--skip-cleanup", action="store_true")
    args = parser.parse_args()
    dry_run = str(args.dry_run).lower() in {"1", "true", "yes"}
    raise SystemExit(
        run(
            slot=args.slot,
            target_date=args.target_date,
            dry_run=dry_run,
            skip_cleanup=args.skip_cleanup,
        )
    )


if __name__ == "__main__":
    main()
