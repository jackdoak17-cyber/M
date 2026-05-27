"""Send the weekly roundup newsletter to an explicit opt-in CSV list."""

from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.marketing_email.send_weekly_roundup_preview import (
    DEFAULT_HTML_PATH,
    PROJECT_ROOT,
    load_html,
    render_text,
    send_email,
)


DEFAULT_SUBSCRIBERS_PATH = PROJECT_ROOT / "data" / "newsletter_subscribers.csv"
DEFAULT_SEND_LOG_PATH = PROJECT_ROOT / "data" / "newsletter_send_log.jsonl"


@dataclass(frozen=True)
class Subscriber:
    email: str
    first_name: str
    source: str
    consent_date: str
    unsubscribe_url: str


def clean(value: str | None) -> str:
    return (value or "").strip()


def load_subscribers(path: Path) -> list[Subscriber]:
    subscribers: list[Subscriber] = []
    seen: set[str] = set()

    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        required = {"email", "status"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"Subscriber CSV is missing columns: {', '.join(sorted(missing))}")

        for row_number, row in enumerate(reader, start=2):
            email = clean(row.get("email")).lower()
            status = clean(row.get("status")).lower()
            if not email or status != "subscribed":
                continue
            if "@" not in email:
                raise ValueError(f"Invalid email at row {row_number}: {email}")
            if email in seen:
                continue
            seen.add(email)
            subscribers.append(
                Subscriber(
                    email=email,
                    first_name=clean(row.get("first_name")),
                    source=clean(row.get("source")),
                    consent_date=clean(row.get("consent_date")),
                    unsubscribe_url=clean(row.get("unsubscribe_url")),
                )
            )

    return subscribers


def inject_newsletter_footer(html: str, unsubscribe_url: str) -> str:
    if "{{UNSUBSCRIBE_URL}}" in html:
        return html.replace("{{UNSUBSCRIBE_URL}}", unsubscribe_url)
    footer = f"""
      <section style="max-width: 860px; margin: 18px auto 0; padding: 14px 18px; color: #94a3b8; font: 12px/1.6 Inter, Arial, sans-serif; text-align: center;">
        You are receiving this because you signed up for OddsSearch updates.
        <a href="{unsubscribe_url}" style="color: #f5a524; text-decoration: underline;">Unsubscribe</a>
      </section>
    """
    if "</main>" in html:
        return html.replace("</main>", f"{footer}\n    </main>", 1)
    return html.replace("</body>", f"{footer}\n  </body>", 1)


def build_payload(
    *,
    html: str,
    subscriber: Subscriber,
    from_email: str,
    subject: str,
    reply_to: str | None,
    fallback_unsubscribe_url: str | None,
    site_url: str | None,
) -> dict[str, Any]:
    unsubscribe_url = subscriber.unsubscribe_url or clean(fallback_unsubscribe_url)
    personalized_html = inject_newsletter_footer(html, unsubscribe_url)
    default_unsubscribe_url = (site_url or "https://oddssearch.io").rstrip("/") + "/unsubscribe"
    text = render_text(site_url).replace(default_unsubscribe_url, unsubscribe_url)
    payload: dict[str, Any] = {
        "from": from_email,
        "to": [subscriber.email],
        "subject": subject,
        "html": personalized_html,
        "text": text,
        "headers": {
            "List-Unsubscribe": f"<{unsubscribe_url}>",
        },
        "tags": [
            {"name": "workflow", "value": "weekly_roundup_newsletter"},
            {"name": "source", "value": "marketing_repo"},
        ],
    }
    if reply_to:
        payload["reply_to"] = reply_to
    return payload


def append_log(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True) + "\n")


def parse_args() -> argparse.Namespace:
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv(PROJECT_ROOT / ".env.local", override=True)

    parser = argparse.ArgumentParser(description="Send the weekly roundup newsletter to opt-in subscribers.")
    parser.add_argument("--send", action="store_true", help="Actually send. Without this, the script dry-runs.")
    parser.add_argument("--limit", type=int, default=0, help="Limit recipients for a staged send. 0 means no limit.")
    parser.add_argument("--subscribers-csv", default=str(DEFAULT_SUBSCRIBERS_PATH), help="CSV with opt-in subscribers.")
    parser.add_argument("--send-log", default=str(DEFAULT_SEND_LOG_PATH), help="JSONL send log path.")
    parser.add_argument("--html-path", default=str(DEFAULT_HTML_PATH), help="HTML newsletter file.")
    parser.add_argument(
        "--from-email",
        default=os.getenv("RESEND_NEWSLETTER_FROM") or os.getenv("RESEND_FROM"),
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
    parser.add_argument(
        "--unsubscribe-url",
        default=os.getenv("NEWSLETTER_UNSUBSCRIBE_URL"),
        help="Fallback unsubscribe URL. Required for live send if CSV rows do not include unsubscribe_url.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    subscribers_path = Path(args.subscribers_csv).expanduser().resolve()

    missing = []
    if not subscribers_path.exists():
        missing.append(f"subscriber CSV at {subscribers_path}")
    if not args.from_email:
        missing.append("RESEND_NEWSLETTER_FROM, RESEND_FROM, or --from-email")
    if args.send and not os.getenv("RESEND_API_KEY"):
        missing.append("RESEND_API_KEY")
    if missing:
        print("Missing required settings/files:")
        for item in missing:
            print(f"- {item}")
        return 2

    subscribers = load_subscribers(subscribers_path)
    if args.limit > 0:
        subscribers = subscribers[: args.limit]
    if not subscribers:
        print("No subscribed recipients found.")
        return 0

    unsubscribe_missing = [sub.email for sub in subscribers if not sub.unsubscribe_url and not args.unsubscribe_url]
    if args.send and unsubscribe_missing:
        print("Live newsletter sends need an unsubscribe URL for every recipient.")
        print("Add unsubscribe_url to the CSV or set NEWSLETTER_UNSUBSCRIBE_URL in .env.local.")
        print("Recipients missing unsubscribe URL:")
        for email in unsubscribe_missing[:10]:
            print(f"- {email}")
        return 2

    html = load_html(Path(args.html_path).expanduser().resolve(), args.site_url, replace_unsubscribe=False)
    dry_run_rows = [
        {
            "email": sub.email,
            "first_name": sub.first_name,
            "source": sub.source,
            "consent_date": sub.consent_date,
            "has_unsubscribe_url": bool(sub.unsubscribe_url or args.unsubscribe_url),
        }
        for sub in subscribers
    ]

    if not args.send:
        print("Dry run only. Add --send to send through Resend.")
        print(f"Recipients: {len(subscribers)}")
        print(json.dumps(dry_run_rows, indent=2))
        return 0

    sent = 0
    failed = 0
    api_key = os.environ["RESEND_API_KEY"]
    send_log = Path(args.send_log).expanduser().resolve()
    for subscriber in subscribers:
        payload = build_payload(
            html=html,
            subscriber=subscriber,
            from_email=args.from_email,
            subject=args.subject,
            reply_to=args.reply_to,
            fallback_unsubscribe_url=args.unsubscribe_url,
            site_url=args.site_url,
        )
        timestamp = datetime.now(UTC).isoformat()
        try:
            response = send_email(api_key, payload)
            sent += 1
            append_log(
                send_log,
                {
                    "sent_at": timestamp,
                    "email": subscriber.email,
                    "resend_id": response.get("id") or response.get("data", {}).get("id"),
                    "status": "sent",
                },
            )
            print(f"Sent {subscriber.email}")
        except Exception as error:
            failed += 1
            append_log(
                send_log,
                {
                    "sent_at": timestamp,
                    "email": subscriber.email,
                    "status": "failed",
                    "error": str(error),
                },
            )
            print(f"Failed {subscriber.email}: {error}")

    print(f"Done. Sent={sent} Failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
