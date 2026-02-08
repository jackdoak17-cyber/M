from __future__ import annotations

import requests

from src.prop_bot.config import get_settings


def send_telegram(message: str) -> None:
    settings = get_settings()
    if not settings.use_telegram or not settings.telegram_bot_token or not settings.telegram_chat_id:
        return
    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
    payload = {"chat_id": settings.telegram_chat_id, "text": message}
    try:
        requests.post(url, json=payload, timeout=15)
    except requests.RequestException:
        return
