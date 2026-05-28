"""Send the mock weekly roundup email through Resend.

This is intentionally send-preview only. It reads the email-safe HTML from
weekly_roundup_preview/email.html and sends it to one test inbox.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HTML_PATH = PROJECT_ROOT / "weekly_roundup_preview" / "email.html"
RESEND_EMAILS_URL = "https://api.resend.com/emails"


def preview_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    return f"{timestamp}-{uuid4().hex[:8]}"


def load_html(path: Path, site_url: str | None, *, replace_unsubscribe: bool = True) -> str:
    html = path.read_text(encoding="utf-8")
    if site_url:
        root_url = site_url.rstrip("/")
        signup_url = root_url + "/signup"
        unsubscribe_url = root_url + "/unsubscribe"
        html = html.replace("{{SITE_URL}}", root_url)
        html = html.replace("{{SIGNUP_URL}}", signup_url)
        if replace_unsubscribe:
            html = html.replace("{{UNSUBSCRIBE_URL}}", unsubscribe_url)
        html = html.replace('href="#"', f'href="{signup_url}"')
    return html


def render_text(site_url: str | None) -> str:
    root_url = (site_url or "https://oddssearch.io").rstrip("/")
    return "\n".join(
        [
            "OddsSearch Weekly Digest",
            "",
            "Premier League results recap, Saturday fixture board, one marquee fixture and example strategy watchlists.",
            "",
            "Open OddsSearch:",
            f"{root_url}/signup",
            "",
            "Included in this issue:",
            "- Previous Premier League gameweek review",
            "- Upcoming Premier League weekend preview",
            "- Liverpool vs Man City fixture deep dive",
            "- Example SOT strategy",
            "- Match markets watchlist",
            "",
            "Odds and stats are research tools, not guarantees.",
            "",
            f"Unsubscribe: {root_url}/unsubscribe",
        ]
    )


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    html_path = Path(args.html_path).expanduser().resolve()
    html = load_html(html_path, args.site_url)
    run_id = preview_run_id()
    payload: dict[str, Any] = {
        "from": args.from_email,
        "to": [args.to],
        "subject": f"{args.subject} preview {run_id}",
        "html": html,
        "text": render_text(args.site_url),
        "headers": {
            "X-Entity-Ref-ID": f"weekly-roundup-preview-{run_id}",
        },
        "tags": [
            {"name": "workflow", "value": "weekly_roundup_preview"},
            {"name": "source", "value": "marketing_repo"},
        ],
    }
    if args.reply_to:
        payload["reply_to"] = args.reply_to
    return payload


def send_email(api_key: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(
        RESEND_EMAILS_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}
    if response.status_code >= 400:
        raise RuntimeError(f"Resend returned {response.status_code}: {json.dumps(body, indent=2)}")
    return body


def parse_args() -> argparse.Namespace:
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / ".env.local", override=True)

    parser = argparse.ArgumentParser(description="Send the weekly roundup mock email to a preview inbox.")
    parser.add_argument("--send", action="store_true", help="Actually send the email. Without this, the script dry-runs.")
    parser.add_argument("--to", default=os.getenv("RESEND_PREVIEW_TO"), help="Preview recipient email address.")
    parser.add_argument(
        "--from-email",
        default=os.getenv("RESEND_FROM"),
        help='Sender, for example "OddsSearch <digest@oddssearch.io>".',
    )
    parser.add_argument("--reply-to", default=os.getenv("RESEND_REPLY_TO"), help="Optional reply-to address.")
    parser.add_argument(
        "--subject",
        default=os.getenv("WEEKLY_ROUNDUP_SUBJECT", "OddsSearch Weekly Digest"),
        help="Email subject line.",
    )
    parser.add_argument(
        "--site-url",
        default=os.getenv("ODDSSEARCH_PUBLIC_URL"),
        help="Public website URL used to replace the mock signup link.",
    )
    parser.add_argument("--html-path", default=str(DEFAULT_HTML_PATH), help="HTML file to send.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    missing = []
    if not args.to:
        missing.append("RESEND_PREVIEW_TO or --to")
    if not args.from_email:
        missing.append("RESEND_FROM or --from-email")
    if args.send and not os.getenv("RESEND_API_KEY"):
        missing.append("RESEND_API_KEY")
    if missing:
        print("Missing required settings:")
        for item in missing:
            print(f"- {item}")
        return 2

    payload = build_payload(args)
    if not args.send:
        print("Dry run only. Add --send to send through Resend.")
        print(json.dumps({k: v for k, v in payload.items() if k != "html"}, indent=2))
        print(f"HTML bytes: {len(payload['html'].encode('utf-8'))}")
        return 0

    result = send_email(os.environ["RESEND_API_KEY"], payload)
    print("Resend accepted the preview email:")
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
