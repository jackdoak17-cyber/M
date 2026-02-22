from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()
load_dotenv(".env.local", override=False)


def _get_env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise RuntimeError(f"Missing required env var: {name}")
    return value


@dataclass(frozen=True)
class PostingSettings:
    supabase_url: str
    supabase_service_role_key: str
    telegram_bot_token: str
    telegram_chat_id: str
    timezone: str
    x_consumer_key: str | None
    x_consumer_secret: str | None
    x_access_token: str | None
    x_access_token_secret: str | None
    x_bearer_token: str | None


def get_posting_settings() -> PostingSettings:
    return PostingSettings(
        supabase_url=_get_env("SUPABASE_URL", required=True) or "",
        supabase_service_role_key=_get_env("SUPABASE_SERVICE_ROLE_KEY", required=True) or "",
        telegram_bot_token=_get_env("ODDS_ANALYST_X_POST_BOT_TOKEN", required=True) or "",
        telegram_chat_id=_get_env("TELEGRAM_CHAT_ID", required=True) or "",
        timezone=_get_env("PROP_SHEET_TIMEZONE", "Europe/London") or "Europe/London",
        x_consumer_key=_get_env("CONSUMER_KEY"),
        x_consumer_secret=_get_env("CLIENT_SECRET"),
        x_access_token=_get_env("ACCESS_TOKEN"),
        x_access_token_secret=_get_env("CLIENT_SECRET_ID"),
        x_bearer_token=_get_env("BEARER_TOKEN"),
    )
