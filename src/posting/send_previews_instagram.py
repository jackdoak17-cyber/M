from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.instagram.assets import enrich_manifest_with_cached_assets
from src.instagram.manifest_io import latest_shot_props_manifest_ref, load_manifest, shot_props_manifest_path
from src.instagram.r2_storage import R2Settings, R2Storage
from src.instagram.renderer import render_carousel_images
from src.instagram.shot_props_manifest import verify_shot_props_carousel_manifest

from .instagram_slots import build_post_key, get_instagram_slot, resolve_instagram_scheduled_date
from .settings import get_posting_settings
from .supabase_client import upsert_post_approval
from .telegram_client import send_media_group, send_message


TELEGRAM_MAX = 3500
INSTAGRAM_MAX_CAROUSEL_ITEMS = 10


def _truncate_text(text: str, limit: int = TELEGRAM_MAX) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 20].rstrip() + "\n\n[...truncated]"


def _content_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _content_type_for_ext(ext: str) -> str:
    normalized = ext.lower().lstrip(".")
    if normalized in {"jpg", "jpeg"}:
        return "image/jpeg"
    if normalized == "png":
        return "image/png"
    raise ValueError(f"Unsupported image extension: {ext}")


def _require_r2_storage() -> R2Storage:
    settings = get_posting_settings()
    missing = [
        name
        for name, value in [
            ("CLOUDFLARE_R2_ACCESS_KEY", settings.cloudflare_r2_access_key),
            ("CLOUDFLARE_R2_SECRET_KEY", settings.cloudflare_r2_secret_key),
            ("CLOUDFLARE_R2_BUCKET_NAME", settings.cloudflare_r2_bucket_name),
            ("CLOUDFLARE_R2_PUBLIC_URL", settings.cloudflare_r2_public_url),
            ("S3_API_ENDPOINT", settings.s3_api_endpoint),
        ]
        if not value
    ]
    if missing:
        raise RuntimeError(f"Missing required R2 env vars for Instagram preview: {', '.join(missing)}")
    return R2Storage(
        R2Settings(
            access_key_id=settings.cloudflare_r2_access_key or "",
            secret_access_key=settings.cloudflare_r2_secret_key or "",
            bucket_name=settings.cloudflare_r2_bucket_name or "",
            public_base_url=settings.cloudflare_r2_public_url or "",
            endpoint_url=settings.s3_api_endpoint or "",
        )
    )


def _render_output_dir(slot: str, scheduled_for: str, content_fingerprint: str) -> Path:
    short = content_fingerprint[:12]
    return Path("output/shot_props/instagram_publish") / f"{scheduled_for}_{slot}_{short}"


def _upload_prefix(slot: str, scheduled_for: str, content_fingerprint: str) -> str:
    short = content_fingerprint[:12]
    return f"instagram/shot_props/{scheduled_for}/{slot}/{short}"


def _build_preview_summary(slot_label: str, scheduled_for: str, manifest: dict[str, Any], image_urls: list[str]) -> str:
    counts = (manifest.get("counts") or {}).get("by_section") or {}
    count_bits = [f"{k}={v}" for k, v in counts.items()]
    slide_count = len(manifest.get("slides") or [])
    lines = [
        f"Instagram Preview: {slot_label}",
        f"Date: {scheduled_for}",
        f"Slides: {slide_count}",
        f"Rows: {(manifest.get('counts') or {}).get('total_rows', 0)}",
    ]
    if count_bits:
        lines.append("Sections: " + ", ".join(count_bits))
    asset_cache = manifest.get("asset_cache") or {}
    if asset_cache:
        lines.append(
            "Assets: "
            f"faces {asset_cache.get('player_cached', 0)}/{asset_cache.get('player_requested', 0)}, "
            f"badges {asset_cache.get('team_cached', 0)}/{asset_cache.get('team_requested', 0)}"
        )
    lines.append("")
    lines.append("Caption:")
    lines.append(_truncate_text(str(manifest.get("caption") or ""), limit=2000))
    lines.append("")
    lines.append(f"Image URLs uploaded: {len(image_urls)}")
    return _truncate_text("\n".join(lines))


def _resolve_manifest_path(slot_cfg: Any, scheduled_for: Any) -> tuple[Path, str]:
    manifest_path = shot_props_manifest_path(slot_cfg.post_type, scheduled_for)
    if manifest_path.exists():
        return manifest_path, scheduled_for.isoformat()
    latest = latest_shot_props_manifest_ref(slot_cfg.post_type)
    if latest is None or not latest.path.exists():
        return manifest_path, scheduled_for.isoformat()
    return latest.path, latest.scheduled_for.isoformat()


def run(
    *,
    slot: str,
    target_date: str | None = None,
    image_ext: str = "png",
    playwright_channel: str | None = None,
    dry_run_upload: bool = False,
) -> int:
    slot_cfg = get_instagram_slot(slot)
    scheduled_for = resolve_instagram_scheduled_date(target_date)
    manifest_path, scheduled_str = _resolve_manifest_path(slot_cfg, scheduled_for)
    if not manifest_path.exists():
        print(f"No Instagram manifest found for slot={slot} scheduled_for={scheduled_str}: {manifest_path}")
        return 0

    manifest = load_manifest(manifest_path)
    issues = verify_shot_props_carousel_manifest(manifest)
    if issues:
        raise RuntimeError("Manifest verification failed:\n" + "\n".join(issues))
    manifest, asset_report = enrich_manifest_with_cached_assets(manifest)

    slides = list(manifest.get("slides") or [])
    if len(slides) > INSTAGRAM_MAX_CAROUSEL_ITEMS:
        raise RuntimeError(
            f"Manifest has {len(slides)} slides but Instagram carousel max is {INSTAGRAM_MAX_CAROUSEL_ITEMS}. "
            "Multi-carousel splitting is required for this post."
        )

    content_fingerprint = str(manifest.get("content_fingerprint") or "")
    if not content_fingerprint:
        raise RuntimeError(f"Manifest missing content_fingerprint: {manifest_path}")

    output_dir = _render_output_dir(slot, scheduled_str, content_fingerprint)
    settings = get_posting_settings()
    rendered = render_carousel_images(
        manifest,
        output_dir,
        manifest_path=manifest_path,
        image_ext=image_ext,
        browser_channel=playwright_channel or settings.instagram_render_playwright_channel,
    )

    image_files = [slide.path for slide in rendered.slides]
    content_type = _content_type_for_ext(image_ext)
    image_urls: list[str] = []
    image_keys: list[str] = []
    if dry_run_upload:
        image_urls = [str(p.resolve().as_uri()) for p in image_files]
    else:
        r2 = _require_r2_storage()
        prefix = _upload_prefix(slot, scheduled_str, content_fingerprint)
        uploads = r2.upload_files(
            [
                (path, f"{prefix}/{path.name}", content_type)
                for path in image_files
            ]
        )
        image_urls = [u.url for u in uploads]
        image_keys = [u.key for u in uploads]

    render_manifest_path = output_dir / "render_manifest.json"
    render_manifest = json.loads(render_manifest_path.read_text(encoding="utf-8"))
    preview_payload = {
        "channel": "instagram",
        "slot": slot,
        "post_type": slot,
        "scheduled_for": scheduled_str,
        "manifest_path": str(manifest_path),
        "manifest_content_fingerprint": content_fingerprint,
        "manifest_counts": manifest.get("counts") or {},
        "caption": manifest.get("caption") or "",
        "image_urls": image_urls,
        "image_keys": image_keys,
        "render_manifest_path": str(render_manifest_path),
        "render_manifest": render_manifest,
        "uploaded_via_r2": not dry_run_upload,
        "asset_cache": asset_report.as_dict(),
        "updated_at": _utc_now_iso(),
    }

    post_key = build_post_key(slot, scheduled_for)
    approval_payload = {
        "post_key": post_key,
        "slot": slot,
        "post_type": slot,
        "post_date": scheduled_str,
        "scheduled_for": scheduled_str,
        "status": "pending",
        "content_path": str(manifest_path),
        "content": json.dumps(preview_payload, ensure_ascii=False, sort_keys=True),
        "content_hash": _content_hash(preview_payload),
        "updated_at": _utc_now_iso(),
    }
    upsert_post_approval(approval_payload)

    media = [{"type": "photo", "media": url} for url in image_urls]
    if media:
        send_media_group(media)
    summary = _build_preview_summary(slot_cfg.label, scheduled_str, manifest, image_urls)
    buttons = [
        [{"text": "✅ Post to Instagram", "callback_data": f"approve:{slot}:{scheduled_str}"}],
        [{"text": "❌ Skip", "callback_data": f"reject:{slot}:{scheduled_str}"}],
    ]
    send_message(summary, buttons=buttons)
    print(f"Instagram preview sent for {post_key} ({len(image_urls)} images)")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Send Telegram previews for Instagram carousel posts.")
    parser.add_argument("--slot", required=True, choices=["ig_shot_props_value", "ig_shot_props_high_prob"])
    parser.add_argument("--date", dest="target_date", help="Scheduled post date (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--image-ext", default="png", choices=["jpeg", "jpg", "png"])
    parser.add_argument("--playwright-channel", choices=["chrome", "chrome-beta", "msedge", "msedge-dev"])
    parser.add_argument(
        "--dry-run-upload",
        action="store_true",
        help="Skip R2 upload and send local file:// URIs (local testing only; Telegram may not accept).",
    )
    args = parser.parse_args()
    raise SystemExit(
        run(
            slot=args.slot,
            target_date=args.target_date,
            image_ext=args.image_ext,
            playwright_channel=args.playwright_channel,
            dry_run_upload=args.dry_run_upload,
        )
    )


if __name__ == "__main__":
    main()
