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
class Settings:
    supabase_db_url: str
    supabase_url: str | None
    supabase_anon_key: str | None
    supabase_service_role_key: str | None
    premier_league_id: int
    bet365_bookmaker_id: int
    timezone: str


def get_settings() -> Settings:
    return Settings(
        supabase_db_url=_get_env("SUPABASE_DB_URL", required=True) or "",
        supabase_url=_get_env("NEXT_PUBLIC_SUPABASE_URL"),
        supabase_anon_key=_get_env("NEXT_PUBLIC_SUPABASE_ANON_KEY"),
        supabase_service_role_key=_get_env("SUPABASE_SERVICE_ROLE_KEY"),
        premier_league_id=int(_get_env("PREMIER_LEAGUE_LEAGUE_ID", "8") or 8),
        bet365_bookmaker_id=int(_get_env("BET365_BOOKMAKER_ID", "2") or 2),
        timezone=_get_env("PROP_SHEET_TIMEZONE", "Europe/London") or "Europe/London",
    )
