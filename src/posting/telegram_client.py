from __future__ import annotations

import json
from typing import Any

import requests

from .settings import get_posting_settings


def _base_url() -> str:
    settings = get_posting_settings()
    return f"https://api.telegram.org/bot{settings.telegram_bot_token}"


def send_message(text: str, buttons: list[list[dict[str, str]]] | None = None) -> dict[str, Any]:
    settings = get_posting_settings()
    payload: dict[str, Any] = {
        "chat_id": settings.telegram_chat_id,
        "text": text,
        "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    response = requests.post(f"{_base_url()}/sendMessage", json=payload, timeout=20)
    response.raise_for_status()
    return response.json()


def send_photo(
    photo: str,
    caption: str | None = None,
    buttons: list[list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    settings = get_posting_settings()
    payload: dict[str, Any] = {
        "chat_id": settings.telegram_chat_id,
        "photo": photo,
    }
    if caption:
        payload["caption"] = caption
    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})
    response = requests.post(f"{_base_url()}/sendPhoto", json=payload, timeout=20)
    response.raise_for_status()
    return response.json()


def send_media_group(media: list[dict[str, Any]]) -> dict[str, Any]:
    settings = get_posting_settings()
    payload: dict[str, Any] = {
        "chat_id": settings.telegram_chat_id,
        "media": media,
    }
    response = requests.post(f"{_base_url()}/sendMediaGroup", json=payload, timeout=30)
    response.raise_for_status()
    return response.json()


def answer_callback(callback_id: str, text: str | None = None) -> None:
    payload: dict[str, Any] = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    response = requests.post(f"{_base_url()}/answerCallbackQuery", json=payload, timeout=20)
    response.raise_for_status()


def delete_webhook(drop_pending_updates: bool = False) -> None:
    payload: dict[str, Any] = {}
    if drop_pending_updates:
        payload["drop_pending_updates"] = True
    response = requests.post(f"{_base_url()}/deleteWebhook", json=payload, timeout=20)
    response.raise_for_status()


def get_updates(offset: int | None = None, timeout_sec: int = 10) -> dict[str, Any]:
    payload: dict[str, Any] = {"timeout": timeout_sec}
    if offset is not None:
        payload["offset"] = offset
    response = requests.get(f"{_base_url()}/getUpdates", params=payload, timeout=timeout_sec + 5)
    response.raise_for_status()
    return response.json()
