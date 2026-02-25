from __future__ import annotations

import os
from urllib.parse import urlparse
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
load_dotenv(".env.local", override=False)

# Local dev convenience: support sibling repo secret files without affecting CI.
_REPO_ROOT = Path(__file__).resolve().parents[2]
for _env_path in (
    _REPO_ROOT / ".env.local",
    _REPO_ROOT / ".env2",
    _REPO_ROOT / ".env2.txt",
    _REPO_ROOT.parent / "statswebsite-web" / ".env.local",
    _REPO_ROOT.parent / "statswebsite-web" / ".env2",
    _REPO_ROOT.parent / "statswebsite-web" / ".env2.txt",
):
    if _env_path.exists():
        load_dotenv(_env_path, override=False)


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
    instagram_access_token: str | None
    instagram_account_id: str | None
    meta_app_id: str | None
    meta_app_secret: str | None
    cloudflare_r2_access_key: str | None
    cloudflare_r2_secret_key: str | None
    cloudflare_r2_bucket_name: str | None
    cloudflare_r2_public_url: str | None
    cloudflare_r2_account_id: str | None
    s3_api_endpoint: str | None
    instagram_render_playwright_channel: str | None


def _derive_supabase_url() -> str | None:
    raw_url = _get_env("SUPABASE_URL") or _get_env("NEXT_PUBLIC_SUPABASE_URL")
    if raw_url:
        if raw_url.endswith(".supabase.com"):
            return raw_url.replace(".supabase.com", ".supabase.co")
        return raw_url

    db_url = _get_env("SUPABASE_DB_URL")
    if not db_url:
        return None

    parsed = urlparse(db_url)
    if not parsed.username:
        return None

    # SUPABASE_DB_URL username looks like "postgres.<project_ref>"
    parts = parsed.username.split(".")
    if len(parts) < 2:
        return None
    project_ref = parts[1]
    return f"https://{project_ref}.supabase.co"


def get_posting_settings() -> PostingSettings:
    supabase_url = _derive_supabase_url()
    if not supabase_url:
        raise RuntimeError("Missing required env var: SUPABASE_URL (or NEXT_PUBLIC_SUPABASE_URL)")
    return PostingSettings(
        supabase_url=supabase_url,
        supabase_service_role_key=_get_env("SUPABASE_SERVICE_ROLE_KEY", required=True) or "",
        telegram_bot_token=(
            _get_env("ODDS_ANALYST_X_POST_BOT_TOKEN") or _get_env("TELEGRAM_BOT_TOKEN", required=True) or ""
        ),
        telegram_chat_id=_get_env("TELEGRAM_CHAT_ID", required=True) or "",
        timezone=_get_env("PROP_SHEET_TIMEZONE", "Europe/London") or "Europe/London",
        x_consumer_key=_get_env("X_CONSUMER_KEY") or _get_env("CONSUMER_KEY"),
        x_consumer_secret=_get_env("X_CONSUMER_SECRET") or _get_env("CLIENT_SECRET"),
        x_access_token=_get_env("X_ACCESS_TOKEN") or _get_env("ACCESS_TOKEN"),
        x_access_token_secret=_get_env("X_ACCESS_TOKEN_SECRET") or _get_env("CLIENT_SECRET_ID"),
        x_bearer_token=_get_env("X_BEARER_TOKEN") or _get_env("BEARER_TOKEN"),
        instagram_access_token=_get_env("INSTAGRAM_ACCESS_TOKEN"),
        instagram_account_id=_get_env("INSTAGRAM_ACCOUNT_ID"),
        meta_app_id=_get_env("META_APP_ID"),
        meta_app_secret=_get_env("META_APP_SECRET"),
        cloudflare_r2_access_key=_get_env("CLOUDFLARE_R2_ACCESS_KEY"),
        cloudflare_r2_secret_key=_get_env("CLOUDFLARE_R2_SECRET_KEY"),
        cloudflare_r2_bucket_name=_get_env("CLOUDFLARE_R2_BUCKET_NAME"),
        cloudflare_r2_public_url=_get_env("CLOUDFLARE_R2_PUBLIC_URL"),
        cloudflare_r2_account_id=_get_env("CLOUDFLARE_R2_ACCOUNT_ID"),
        s3_api_endpoint=_get_env("S3_API_ENDPOINT"),
        instagram_render_playwright_channel=_get_env("INSTAGRAM_RENDER_PLAYWRIGHT_CHANNEL"),
    )
