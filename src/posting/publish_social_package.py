from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import UUID

import requests

from src.instagram.meta_graph import InstagramGraphClient, MetaGraphSettings


PUBLISH_CONFIRMATION = "PUBLISH INSTAGRAM"
ACCOUNT_KEY = "oddssearch-main"


@dataclass(frozen=True)
class PackagePublishResult:
    post_id: str
    media_id: str
    permalink: str | None
    image_count: int
    published_at: str


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _supabase_base() -> str:
    return _required_env("SUPABASE_URL").rstrip("/")


def _supabase_headers(*, representation: bool = False) -> dict[str, str]:
    key = _required_env("SUPABASE_SERVICE_ROLE_KEY")
    headers = {
        "Authorization": f"Bearer {key}",
        "apikey": key,
        "Content-Type": "application/json",
    }
    if representation:
        headers["Prefer"] = "return=representation"
    return headers


def _safe_error(error: Exception) -> str:
    message = re.sub(r"https?://\S+", "[external service]", str(error))
    return message[:500] or "Instagram package publishing failed."


def _warning_messages(warnings: Any) -> list[str]:
    if not isinstance(warnings, list):
        return []
    messages: list[str] = []
    for warning in warnings:
        if isinstance(warning, str):
            messages.append(warning)
        elif isinstance(warning, dict) and isinstance(warning.get("message"), str):
            messages.append(warning["message"])
    return messages


def validate_package(package: dict[str, Any], *, post_id: str, account_key: str) -> None:
    if str(package.get("id")) != post_id or package.get("account_key") != account_key:
        raise RuntimeError("The package does not belong to the requested account.")
    if package.get("status") != "publishing":
        raise RuntimeError("The package is not in the publishing state.")
    if package.get("posted_instagram_id"):
        raise RuntimeError("The package is already published to Instagram.")
    channels = [str(channel).lower() for channel in package.get("channels") or []]
    if "instagram" not in channels:
        raise RuntimeError("The package is not assigned to Instagram.")

    caption = str(package.get("instagram_caption") or package.get("generated_instagram_caption") or "").strip()
    if not 1 <= len(caption) <= 2200:
        raise RuntimeError("The Instagram caption must contain between 1 and 2200 characters.")
    image_urls = package.get("instagram_image_urls") or []
    if not image_urls or not all(isinstance(url, str) and url.startswith("https://") for url in image_urls):
        raise RuntimeError("The package requires durable HTTPS media.")
    if any(
        re.search(r"do not publish|mock data|blocking", message, re.IGNORECASE)
        for message in _warning_messages(package.get("warnings"))
    ):
        raise RuntimeError("A package warning blocks Instagram publishing.")


def publish_package(
    package: dict[str, Any],
    *,
    post_id: str,
    account_key: str,
    client: InstagramGraphClient,
) -> PackagePublishResult:
    validate_package(package, post_id=post_id, account_key=account_key)
    caption = str(package.get("instagram_caption") or package.get("generated_instagram_caption") or "").strip()
    image_urls = list(package["instagram_image_urls"])

    if len(image_urls) == 1:
        container_id = client.create_image_container(
            image_urls[0],
            is_carousel_item=False,
            caption=caption,
        )
        client.wait_for_container_ready(container_id)
        media_id = client.publish_container(container_id)
    else:
        media_id = client.create_and_publish_carousel(image_urls, caption).media_id

    permalink: str | None = None
    try:
        media = client.get_media(media_id, fields="id,permalink")
        if media.get("permalink"):
            permalink = str(media["permalink"])
    except Exception:
        permalink = None

    return PackagePublishResult(
        post_id=post_id,
        media_id=media_id,
        permalink=permalink,
        image_count=len(image_urls),
        published_at=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    )


def _fetch_package(post_id: str, account_key: str) -> dict[str, Any]:
    response = requests.get(
        f"{_supabase_base()}/rest/v1/social_post_packages",
        headers=_supabase_headers(),
        params={
            "id": f"eq.{post_id}",
            "account_key": f"eq.{account_key}",
            "brand_key": "eq.oddssearch",
            "select": "*",
        },
        timeout=20,
    )
    response.raise_for_status()
    rows = response.json() or []
    if len(rows) != 1:
        raise RuntimeError("The requested social package was not found.")
    return rows[0]


def _patch_package(post_id: str, account_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.patch(
        f"{_supabase_base()}/rest/v1/social_post_packages",
        headers=_supabase_headers(representation=True),
        params={
            "id": f"eq.{post_id}",
            "account_key": f"eq.{account_key}",
            "brand_key": "eq.oddssearch",
        },
        json=payload,
        timeout=20,
    )
    response.raise_for_status()
    rows = response.json() or []
    if len(rows) != 1:
        raise RuntimeError("The package update did not match exactly one record.")
    return rows[0]


def _record_event(post_id: str, event_type: str, details: dict[str, Any]) -> None:
    response = requests.post(
        f"{_supabase_base()}/rest/v1/social_post_events",
        headers=_supabase_headers(),
        json={"post_id": post_id, "event_type": event_type, "details": details},
        timeout=20,
    )
    response.raise_for_status()


def _client_from_env() -> InstagramGraphClient:
    return InstagramGraphClient(
        MetaGraphSettings(
            instagram_account_id=_required_env("INSTAGRAM_ACCOUNT_ID"),
            access_token=_required_env("INSTAGRAM_ACCESS_TOKEN"),
        )
    )


def run(
    *,
    confirmation: str,
    post_id: str,
    account_key: str,
    workflow_run_id: str,
    client_factory: Callable[[], InstagramGraphClient] = _client_from_env,
) -> PackagePublishResult:
    if confirmation != PUBLISH_CONFIRMATION:
        raise RuntimeError(f"Live publishing requires the exact {PUBLISH_CONFIRMATION} confirmation.")
    if account_key != ACCOUNT_KEY:
        raise RuntimeError("Only the OddsSearch main account is enabled.")
    UUID(post_id)
    if not workflow_run_id.strip():
        raise RuntimeError("A workflow run identifier is required.")

    package = _fetch_package(post_id, account_key)
    validate_package(package, post_id=post_id, account_key=account_key)
    previous_result = (package.get("post_results") or {}).get("instagram") or {}
    if previous_result.get("workflow_run_id"):
        raise RuntimeError(
            "This package already has an Instagram workflow marker. Reconcile it before retrying."
        )

    post_results = dict(package.get("post_results") or {})
    post_results["instagram"] = {
        "workflow_run_id": workflow_run_id,
        "state": "publishing",
    }
    package = _patch_package(post_id, account_key, {"post_results": post_results})

    try:
        result = publish_package(
            package,
            post_id=post_id,
            account_key=account_key,
            client=client_factory(),
        )
        channels = [str(channel).lower() for channel in package.get("channels") or []]
        x_pending = "x" in channels and not package.get("posted_x_id")
        post_results["instagram"] = {
            "workflow_run_id": workflow_run_id,
            "state": "posted",
            "media_id": result.media_id,
            "permalink": result.permalink,
            "image_count": result.image_count,
        }
        _patch_package(
            post_id,
            account_key,
            {
                "posted_instagram_id": result.media_id,
                "posted_at": None if x_pending else result.published_at,
                "status": "approved" if x_pending else "posted",
                "post_results": post_results,
                "error": None,
            },
        )
        _record_event(
            post_id,
            "operations:posted:instagram",
            {
                "actor": "github-actions",
                "platform": "instagram",
                "external_id": result.media_id,
                "workflow_run_id": workflow_run_id,
            },
        )
        print(
            json.dumps(
                {
                    "status": "published",
                    "post_id": result.post_id,
                    "media_id": result.media_id,
                    "image_count": result.image_count,
                },
                sort_keys=True,
            )
        )
        return result
    except Exception as error:
        safe_error = _safe_error(error)
        try:
            post_results["instagram"] = {
                "workflow_run_id": workflow_run_id,
                "state": "failed",
                "error": safe_error,
            }
            _patch_package(
                post_id,
                account_key,
                {"status": "failed", "post_results": post_results, "error": safe_error},
            )
            _record_event(
                post_id,
                "operations:failed:instagram",
                {
                    "actor": "github-actions",
                    "platform": "instagram",
                    "error": safe_error,
                    "workflow_run_id": workflow_run_id,
                },
            )
        finally:
            raise


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish one approved social package to Instagram.")
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--post-id", required=True)
    parser.add_argument("--account-key", required=True)
    parser.add_argument("--workflow-run-id", required=True)
    args = parser.parse_args()
    run(
        confirmation=args.confirmation,
        post_id=args.post_id,
        account_key=args.account_key,
        workflow_run_id=args.workflow_run_id,
    )


if __name__ == "__main__":
    main()
