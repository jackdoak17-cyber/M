from __future__ import annotations

import argparse
import html
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import sleep
from typing import Callable

import requests

from src.instagram.meta_graph import InstagramGraphClient, MetaGraphSettings
from src.instagram.r2_storage import R2Settings, R2Storage
from src.instagram.renderer import PLAYWRIGHT_PKG_DEFAULT, _run_playwright_screenshot


PUBLISH_CONFIRMATION = "PUBLISH_TEST"
DEFAULT_CAPTION = (
    "OddsSearch publishing connection verified.\n\n"
    "Automated system test. This post can be removed."
)


@dataclass(frozen=True)
class InstagramConnectionTestResult:
    status: str
    media_id: str
    permalink: str | None
    published_at: str
    run_label: str


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def _safe_run_label(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-")
    if not normalized:
        raise ValueError("run_label must contain at least one letter or number")
    return normalized[:80]


def _test_card_html(*, run_label: str, generated_at: datetime) -> str:
    safe_label = html.escape(run_label)
    timestamp = generated_at.astimezone(timezone.utc).strftime("%d %b %Y · %H:%M UTC")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{
      width: 1080px;
      height: 1350px;
      margin: 0;
      overflow: hidden;
      background: #07090c;
      color: #f4f6f8;
      font-family: Arial, Helvetica, sans-serif;
    }}
    body {{
      display: grid;
      grid-template-rows: auto 1fr auto;
      padding: 72px;
      border: 2px solid #2b333d;
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      border-bottom: 1px solid #2b333d;
      padding-bottom: 32px;
    }}
    .brand {{
      font-size: 28px;
      font-weight: 700;
      letter-spacing: 0;
    }}
    .mode {{
      color: #96a2ae;
      font-size: 20px;
      letter-spacing: 0;
      text-transform: uppercase;
    }}
    main {{
      display: flex;
      flex-direction: column;
      justify-content: center;
      max-width: 850px;
    }}
    .signal {{
      width: 18px;
      height: 18px;
      margin-bottom: 38px;
      background: #42d392;
      box-shadow: 0 0 28px rgba(66, 211, 146, 0.55);
    }}
    h1 {{
      max-width: 820px;
      margin: 0;
      font-size: 104px;
      line-height: 0.98;
      font-weight: 600;
      letter-spacing: 0;
    }}
    p {{
      max-width: 700px;
      margin: 42px 0 0;
      color: #aeb7c1;
      font-size: 30px;
      line-height: 1.45;
      letter-spacing: 0;
    }}
    footer {{
      display: flex;
      justify-content: space-between;
      gap: 32px;
      border-top: 1px solid #2b333d;
      padding-top: 30px;
      color: #77838f;
      font-size: 18px;
      letter-spacing: 0;
    }}
  </style>
</head>
<body class="ready">
  <header>
    <div class="brand">ODDSSEARCH</div>
    <div class="mode">Operations · connection test</div>
  </header>
  <main>
    <div class="signal"></div>
    <h1>Publishing link verified.</h1>
    <p>Instagram accepted a live post from the OddsSearch operations system.</p>
  </main>
  <footer>
    <span>{html.escape(timestamp)}</span>
    <span>{safe_label}</span>
  </footer>
</body>
</html>
"""


def render_test_card(
    *,
    output_dir: Path,
    run_label: str,
    generated_at: datetime,
    browser_channel: str | None = None,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    html_path = output_dir / "connection-test.html"
    image_path = output_dir / "connection-test.png"
    html_path.write_text(
        _test_card_html(run_label=run_label, generated_at=generated_at),
        encoding="utf-8",
    )
    _run_playwright_screenshot(
        html_path,
        image_path,
        playwright_pkg=PLAYWRIGHT_PKG_DEFAULT,
        browser_channel=browser_channel,
        timeout_ms=60_000,
    )
    return image_path


def _wait_for_public_image(
    url: str,
    *,
    max_attempts: int = 8,
    delay_seconds: float = 2.0,
) -> None:
    last_status: int | None = None
    for _ in range(max_attempts):
        response = requests.get(url, timeout=20, stream=True)
        last_status = response.status_code
        response.close()
        if 200 <= last_status < 300:
            return
        sleep(delay_seconds)
    raise RuntimeError(f"Test image was not publicly available from R2 (last status: {last_status})")


def publish_test_card(
    *,
    confirmation: str,
    run_label: str,
    image_path: Path,
    storage: R2Storage,
    client: InstagramGraphClient,
    generated_at: datetime,
    public_image_probe: Callable[[str], None] = _wait_for_public_image,
    caption: str = DEFAULT_CAPTION,
) -> InstagramConnectionTestResult:
    if confirmation != PUBLISH_CONFIRMATION:
        raise RuntimeError("Live Instagram test requires the exact PUBLISH_TEST confirmation.")
    if not image_path.is_file():
        raise FileNotFoundError(f"Instagram test image does not exist: {image_path}")

    date_prefix = generated_at.astimezone(timezone.utc).strftime("%Y-%m-%d")
    object_key = f"instagram/connection-tests/{date_prefix}/{run_label}/connection-test.png"
    uploaded = storage.upload_file(
        image_path,
        object_key,
        content_type="image/png",
        cache_control="public, max-age=3600",
    )

    published = False
    try:
        public_image_probe(uploaded.url)
        container_id = client.create_image_container(uploaded.url, is_carousel_item=False)
        client.wait_for_container_ready(container_id)
        media_id = client.publish_container(container_id)
        published = True

        permalink: str | None = None
        try:
            media = client.get_media(media_id, fields="id,permalink")
            value = media.get("permalink")
            permalink = str(value) if value else None
        except Exception as exc:  # noqa: BLE001
            print(f"Instagram test published, but permalink lookup failed: {exc}")

        return InstagramConnectionTestResult(
            status="published",
            media_id=media_id,
            permalink=permalink,
            published_at=generated_at.astimezone(timezone.utc).replace(microsecond=0).isoformat(),
            run_label=run_label,
        )
    finally:
        try:
            storage.delete_keys([uploaded.key])
        except Exception as exc:  # noqa: BLE001
            message = "after publication" if published else "after failed publication"
            print(f"R2 cleanup warning {message}: {exc}")


def _storage_from_env() -> R2Storage:
    return R2Storage(
        R2Settings(
            access_key_id=_required_env("CLOUDFLARE_R2_ACCESS_KEY"),
            secret_access_key=_required_env("CLOUDFLARE_R2_SECRET_KEY"),
            bucket_name=_required_env("CLOUDFLARE_R2_BUCKET_NAME"),
            public_base_url=_required_env("CLOUDFLARE_R2_PUBLIC_URL"),
            endpoint_url=_required_env("S3_API_ENDPOINT"),
        )
    )


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
    run_label: str,
    output_dir: Path,
    browser_channel: str | None = None,
) -> InstagramConnectionTestResult:
    if confirmation != PUBLISH_CONFIRMATION:
        raise RuntimeError("Live Instagram test requires the exact PUBLISH_TEST confirmation.")

    safe_label = _safe_run_label(run_label)
    generated_at = _utc_now()
    image_path = render_test_card(
        output_dir=output_dir,
        run_label=safe_label,
        generated_at=generated_at,
        browser_channel=browser_channel,
    )
    result = publish_test_card(
        confirmation=confirmation,
        run_label=safe_label,
        image_path=image_path,
        storage=_storage_from_env(),
        client=_client_from_env(),
        generated_at=generated_at,
    )
    result_path = output_dir / "result.json"
    result_path.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
    print(json.dumps(asdict(result), sort_keys=True))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Publish one explicit live image to verify the Instagram connection."
    )
    parser.add_argument("--confirmation", required=True)
    parser.add_argument("--run-label", required=True)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output/instagram_connection_test"),
    )
    parser.add_argument("--playwright-channel", choices=["chrome", "chrome-beta", "msedge", "msedge-dev"])
    args = parser.parse_args()
    run(
        confirmation=args.confirmation,
        run_label=args.run_label,
        output_dir=args.output_dir,
        browser_channel=args.playwright_channel,
    )


if __name__ == "__main__":
    main()
