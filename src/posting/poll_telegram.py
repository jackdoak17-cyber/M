from __future__ import annotations

import argparse

from .supabase_client import fetch_post_approval, fetch_telegram_state, update_post_status, update_telegram_state
from .telegram_client import answer_callback, delete_webhook, get_updates
from .settings import get_posting_settings


def run() -> int:
    settings = get_posting_settings()
    try:
        delete_webhook()
    except Exception as exc:
        print(f"Warning: failed to clear webhook: {exc}")
    state = fetch_telegram_state()
    offset = state.last_update_id + 1 if state.last_update_id else None
    updates = get_updates(offset=offset, timeout_sec=10)
    if not updates.get("ok"):
        raise SystemExit("Telegram getUpdates failed")

    results = updates.get("result", [])
    if not results:
        print("No telegram updates")
        return 0

    max_update_id = state.last_update_id
    for item in results:
        update_id = item.get("update_id")
        if update_id is not None:
            max_update_id = max(max_update_id, int(update_id))
        callback = item.get("callback_query")
        if not callback:
            continue
        data = callback.get("data", "")
        callback_id = callback.get("id")
        message = callback.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        if str(chat_id) != str(settings.telegram_chat_id):
            continue

        if ":" not in data:
            continue
        action, post_key = data.split(":", 1)
        approval = fetch_post_approval(post_key)
        if not approval:
            if callback_id:
                answer_callback(callback_id, text="No matching post found.")
            continue

        if action == "approve":
            update_post_status(post_key, "approved")
            if callback_id:
                answer_callback(callback_id, text="Approved.")
        elif action == "reject":
            update_post_status(post_key, "rejected")
            if callback_id:
                answer_callback(callback_id, text="Rejected.")
        else:
            if callback_id:
                answer_callback(callback_id, text="Unknown action.")

    if max_update_id != state.last_update_id:
        update_telegram_state(max_update_id)

    print(f"Processed {len(results)} updates")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Poll Telegram approvals.")
    _ = parser.parse_args()
    raise SystemExit(run())


if __name__ == "__main__":
    main()
