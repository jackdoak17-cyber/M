from __future__ import annotations

import argparse
import hashlib
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .content_resolver import resolve_content
from .settings import get_posting_settings
from .supabase_client import PostApproval, list_post_approvals
from .telegram_client import send_message


DEFAULT_X_SLOTS = [
    "weekend_fixture",
    "weekend_player_100",
    "weekend_player_80",
    "weekday_fixture",
    "weekday_player",
]


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


def _notify_drift(approval: PostApproval, scheduled_for: date) -> None:
    post_key = approval.post_key
    post_date = scheduled_for.isoformat()
    message = (
        "Alert: approved X post differs from latest generated content.\n"
        f"Key: {post_key}\n"
        f"Scheduled: {post_date} ({scheduled_for.strftime('%A')})\n\n"
        "Current behavior: the approved version will still post unless you reject it below."
    )
    buttons = [
        [{"text": "Keep approved", "callback_data": f"approve:{approval.slot}:{post_date}"}],
        [{"text": "Reject post", "callback_data": f"reject:{approval.slot}:{post_date}"}],
    ]
    send_message(message, buttons=buttons)


def run(window_days: int, slots: list[str]) -> int:
    settings = get_posting_settings()
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    end_date = today + timedelta(days=max(window_days, 0))

    approvals = list_post_approvals(status="approved", posted=False, slots=slots)
    alerts_sent = 0

    for approval in approvals:
        scheduled_for = _parse_date(approval.scheduled_for)
        if not scheduled_for:
            continue
        if scheduled_for < today or scheduled_for > end_date:
            continue

        approved_content = (approval.content or "").strip()
        if not approved_content:
            continue

        latest = resolve_content(approval.slot, scheduled_for)
        if latest is None:
            continue

        approved_hash = approval.content_hash or _content_hash(approved_content)
        latest_hash = _content_hash(latest.content)
        if approved_hash == latest_hash:
            continue

        _notify_drift(approval, scheduled_for)
        alerts_sent += 1
        print(f"Drift alert sent for {approval.post_key}")

    print(f"Checked {len(approvals)} approved posts; drift alerts sent: {alerts_sent}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Alert in Telegram when approved X post content drifts from regenerated files.",
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=7,
        help="Only check approved posts scheduled from today to today+N days.",
    )
    parser.add_argument(
        "--slot",
        dest="slots",
        action="append",
        default=[],
        help="Slot to check (repeatable). Defaults to core X slots.",
    )
    args = parser.parse_args()
    slots = args.slots or DEFAULT_X_SLOTS
    raise SystemExit(run(window_days=args.window_days, slots=slots))


if __name__ == "__main__":
    main()
