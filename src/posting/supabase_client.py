from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import requests

from .settings import get_posting_settings


@dataclass(frozen=True)
class PostApproval:
    post_key: str
    slot: str
    scheduled_for: str
    status: str
    content_path: str
    content: str
    content_hash: str | None = None
    post_type: str | None = None
    post_date: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    approved_at: str | None = None
    rejected_at: str | None = None
    posted_at: str | None = None
    posted_tweet_id: str | None = None


@dataclass(frozen=True)
class TelegramState:
    last_update_id: int


def _supabase_headers() -> dict[str, str]:
    settings = get_posting_settings()
    return {
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "apikey": settings.supabase_service_role_key,
        "Content-Type": "application/json",
    }


def _supabase_url(path: str) -> str:
    settings = get_posting_settings()
    base = settings.supabase_url.rstrip("/")
    return f"{base}/rest/v1/{path.lstrip('/')}"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def upsert_post_approval(payload: dict[str, Any]) -> PostApproval:
    url = _supabase_url("post_approvals")
    headers = _supabase_headers()
    headers["Prefer"] = "resolution=merge-duplicates,return=representation"
    params = {"on_conflict": "post_key"}
    response = requests.post(url, headers=headers, params=params, json=payload, timeout=20)
    response.raise_for_status()
    data = response.json()
    record = (data or [None])[0] or {}
    return PostApproval(**record)


def fetch_post_approval(post_key: str) -> PostApproval | None:
    url = _supabase_url("post_approvals")
    params = {"post_key": f"eq.{post_key}", "select": "*"}
    response = requests.get(url, headers=_supabase_headers(), params=params, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not data:
        return None
    return PostApproval(**data[0])


def update_post_status(post_key: str, status: str, extra: dict[str, Any] | None = None) -> PostApproval:
    url = _supabase_url("post_approvals")
    params = {"post_key": f"eq.{post_key}", "select": "*"}
    payload: dict[str, Any] = {
        "status": status,
        "updated_at": _utc_now_iso(),
    }
    if status == "approved":
        payload["approved_at"] = _utc_now_iso()
    if status == "rejected":
        payload["rejected_at"] = _utc_now_iso()
    if extra:
        payload.update(extra)
    headers = _supabase_headers()
    headers["Prefer"] = "return=representation"
    response = requests.patch(url, headers=headers, params=params, json=payload, timeout=20)
    response.raise_for_status()
    data = response.json()
    record = (data or [None])[0] or {}
    return PostApproval(**record)


def fetch_telegram_state() -> TelegramState:
    url = _supabase_url("telegram_state")
    params = {"id": "eq.1", "select": "last_update_id"}
    response = requests.get(url, headers=_supabase_headers(), params=params, timeout=20)
    response.raise_for_status()
    data = response.json()
    if not data:
        return TelegramState(last_update_id=0)
    return TelegramState(last_update_id=int(data[0].get("last_update_id") or 0))


def update_telegram_state(last_update_id: int) -> None:
    url = _supabase_url("telegram_state")
    params = {"id": "eq.1"}
    payload = {
        "last_update_id": int(last_update_id),
        "updated_at": _utc_now_iso(),
    }
    headers = _supabase_headers()
    headers["Prefer"] = "return=representation"
    response = requests.patch(url, headers=headers, params=params, json=payload, timeout=20)
    response.raise_for_status()
