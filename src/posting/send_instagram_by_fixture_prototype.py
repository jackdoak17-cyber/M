from __future__ import annotations

import argparse
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from src.instagram.assets import enrich_manifest_with_cached_assets
from src.instagram.by_fixture_manifest import build_by_fixture_manifest, verify_by_fixture_manifest
from src.instagram.r2_storage import R2Settings, R2Storage
from src.instagram.renderer import render_carousel_images

from .content_resolver import resolve_content, resolve_target_date
from .settings import get_posting_settings
from .telegram_client import send_media_group, send_message


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
        raise RuntimeError(f"Missing required R2 env vars: {', '.join(missing)}")
    return R2Storage(
        R2Settings(
            access_key_id=settings.cloudflare_r2_access_key or "",
            secret_access_key=settings.cloudflare_r2_secret_key or "",
            bucket_name=settings.cloudflare_r2_bucket_name or "",
            public_base_url=settings.cloudflare_r2_public_url or "",
            endpoint_url=settings.s3_api_endpoint or "",
        )
    )


def _manifest_path(slot: str, scheduled_for: str, fingerprint: str) -> Path:
    short = fingerprint[:12]
    return Path("output/instagram_by_fixture/manifests") / f"{scheduled_for}_{slot}_{short}.json"


def _render_dir(slot: str, scheduled_for: str, fingerprint: str) -> Path:
    short = fingerprint[:12]
    return Path("output/instagram_by_fixture/renders") / f"{scheduled_for}_{slot}_{short}"


def _upload_prefix(slot: str, scheduled_for: str, fingerprint: str) -> str:
    short = fingerprint[:12]
    return f"instagram/prototypes/by_fixture/{scheduled_for}/{slot}/{short}/{_render_revision()}"


def _render_revision() -> str:
    sha = os.getenv("GITHUB_SHA", "local")[:7] or "local"
    run_id = os.getenv("GITHUB_RUN_ID", "").strip()
    if run_id:
        return f"{sha}-run{run_id}"
    return f"{sha}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"


def _masked_chat_id(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    if len(text) <= 4:
        return text
    return f"...{text[-4:]}"


def _telegram_target_from_response(payload: Any) -> dict[str, str]:
    chat: dict[str, Any] = {}
    if isinstance(payload, list) and payload:
        first = payload[0]
        if isinstance(first, dict):
            chat = (first.get("chat") or {}) if isinstance(first.get("chat"), dict) else {}
    elif isinstance(payload, dict):
        chat = (payload.get("chat") or {}) if isinstance(payload.get("chat"), dict) else {}
    return {
        "chat_id_masked": _masked_chat_id(chat.get("id")),
        "chat_type": str(chat.get("type") or "unknown"),
        "chat_title": str(chat.get("title") or ""),
        "chat_username": str(chat.get("username") or ""),
    }


def _telegram_probe_marker(slot: str, scheduled_for: str) -> str:
    run_id = os.getenv("GITHUB_RUN_ID", "local")
    sha = os.getenv("GITHUB_SHA", "local")[:7]
    return f"IG-FIXTURE-PROBE {scheduled_for} {slot} run={run_id} sha={sha}"


def _write_delivery_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def run(
    *,
    slot: str,
    target_date: str | None = None,
    image_ext: str = "png",
    playwright_channel: str | None = None,
) -> int:
    scheduled_for = (
        date.fromisoformat(target_date)
        if target_date
        else resolve_target_date("preview", slot=slot)
    )
    scheduled_str = scheduled_for.isoformat()
    info = resolve_content(slot, scheduled_for)
    if info is None:
        raise RuntimeError(f"No content resolved for slot={slot} date={scheduled_str}")

    manifest = build_by_fixture_manifest(
        content_path=info.path,
        scheduled_for=info.scheduled_for.isoformat(),
        content=info.content,
        slot=slot,
        label=info.label,
    )
    asset_report = None
    if os.getenv("SUPABASE_DB_URL"):
        manifest, asset_report = enrich_manifest_with_cached_assets(manifest)
    issues = verify_by_fixture_manifest(manifest)
    if issues:
        raise RuntimeError("By-fixture manifest verification failed:\n" + "\n".join(issues))

    fingerprint = str(manifest.get("content_fingerprint") or "")
    if not fingerprint:
        raise RuntimeError("Manifest missing content_fingerprint")

    manifest_path = _manifest_path(slot, scheduled_str, fingerprint)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    settings = get_posting_settings()
    render_dir = _render_dir(slot, scheduled_str, fingerprint)
    rendered = render_carousel_images(
        manifest,
        render_dir,
        manifest_path=manifest_path,
        image_ext=image_ext,
        browser_channel=playwright_channel or settings.instagram_render_playwright_channel,
    )

    r2 = _require_r2_storage()
    uploads = r2.upload_files(
        [
            (slide.path, f"{_upload_prefix(slot, scheduled_str, fingerprint)}/{slide.path.name}", _content_type_for_ext(image_ext))
            for slide in rendered.slides
        ]
    )
    image_urls = [upload.url for upload in uploads]
    probe = _telegram_probe_marker(slot, scheduled_str)
    delivery_report: dict[str, Any] = {
        "probe": probe,
        "slot": slot,
        "scheduled_for": scheduled_str,
        "generated_at": _utc_now_iso(),
        "image_count": len(image_urls),
        "image_urls": image_urls,
        "github_run_id": os.getenv("GITHUB_RUN_ID", ""),
        "github_sha": os.getenv("GITHUB_SHA", ""),
    }
    probe_result = send_message(f"{probe}\nPreparing by-fixture Instagram prototype preview.")
    delivery_report["probe_message"] = {
        **_telegram_target_from_response((probe_result or {}).get("result") or {}),
        "message_id": ((probe_result or {}).get("result") or {}).get("message_id"),
    }

    if image_urls:
        media_result = send_media_group([{"type": "photo", "media": url} for url in image_urls])
        media_payload = media_result.get("result") if isinstance(media_result, dict) else media_result
        message_ids: list[int] = []
        if isinstance(media_payload, list):
            for item in media_payload:
                if isinstance(item, dict) and isinstance(item.get("message_id"), int):
                    message_ids.append(item["message_id"])
        delivery_report["media_group"] = {
            **_telegram_target_from_response(media_payload),
            "message_ids": message_ids,
            "count": len(message_ids),
        }

    summary_result = send_message(
        "\n".join(
            [
                "Instagram by-fixture prototype sent",
                f"Probe: {probe}",
                f"Slot: {slot}",
                f"Date: {scheduled_str}",
                f"Fixtures/slides: {len(manifest.get('slides') or [])}",
                f"Total rows: {int(((manifest.get('counts') or {}).get('total_rows')) or 0)}",
                f"Source: {info.path}",
                f"Manifest: {manifest_path}",
                f"Rendered at: {render_dir}",
                f"Generated at: {_utc_now_iso()}",
            ]
            + (
                [
                    "Assets: "
                    f"faces {asset_report.player_cached}/{asset_report.player_requested}, "
                    f"badges {asset_report.team_cached}/{asset_report.team_requested}",
                ]
                if asset_report is not None
                else []
            )
        )
    )
    delivery_report["summary_message"] = {
        **_telegram_target_from_response((summary_result or {}).get("result") or {}),
        "message_id": ((summary_result or {}).get("result") or {}).get("message_id"),
    }
    delivery_report_path = render_dir / "delivery_report.json"
    _write_delivery_report(delivery_report_path, delivery_report)
    target = delivery_report.get("summary_message") or delivery_report.get("probe_message") or {}
    print(
        "Telegram delivery target:",
        f"type={target.get('chat_type', 'unknown')}",
        f"title={target.get('chat_title', '') or '-'}",
        f"username={target.get('chat_username', '') or '-'}",
        f"id={target.get('chat_id_masked', 'unknown')}",
    )
    print(f"Telegram probe marker: {probe}")
    print(f"Delivery report: {delivery_report_path}")
    print(f"Sent by-fixture Instagram prototype for {slot} {scheduled_str}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Send by-fixture Instagram prototype to Telegram.")
    parser.add_argument("--slot", required=True, choices=["weekend_fixture", "weekday_fixture"])
    parser.add_argument("--date", dest="target_date")
    parser.add_argument("--image-ext", default="png", choices=["png", "jpg", "jpeg"])
    parser.add_argument("--playwright-channel", choices=["chrome", "chrome-beta", "msedge", "msedge-dev"])
    args = parser.parse_args()
    raise SystemExit(
        run(
            slot=args.slot,
            target_date=args.target_date,
            image_ext=args.image_ext,
            playwright_channel=args.playwright_channel,
        )
    )


if __name__ == "__main__":
    main()
