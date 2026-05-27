"""Send the mock weekly roundup email through Resend.

This is intentionally send-preview only. It reads the static HTML preview from
weekly_roundup_preview/index.html and sends it to one test inbox.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HTML_PATH = PROJECT_ROOT / "weekly_roundup_preview" / "index.html"
RESEND_EMAILS_URL = "https://api.resend.com/emails"


def load_html(path: Path, site_url: str | None) -> str:
    html = path.read_text(encoding="utf-8")
    if site_url:
        signup_url = site_url.rstrip("/") + "/signup"
        html = html.replace('href="#"', f'href="{signup_url}"')
    return html


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    html_path = Path(args.html_path).expanduser().resolve()
    html = load_html(html_path, args.site_url)
    payload: dict[str, Any] = {
        "from": args.from_email,
        "to": [args.to],
        "subject": args.subject,
        "html": html,
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
        help='Sender, for example "OddsSearch <weekly@updates.yourdomain.com>".',
    )
    parser.add_argument("--reply-to", default=os.getenv("RESEND_REPLY_TO"), help="Optional reply-to address.")
    parser.add_argument(
        "--subject",
        default=os.getenv("WEEKLY_ROUNDUP_SUBJECT", "OddsSearch Weekly Roundup + Preview"),
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

