from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.extras import RealDictCursor

from src.prop_bot.config import get_settings


@contextmanager
def db_cursor() -> Iterator[RealDictCursor]:
    settings = get_settings()
    if not settings.supabase_db_url:
        raise RuntimeError("SUPABASE_DB_URL is not set")
    conn = psycopg2.connect(settings.supabase_db_url)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
    finally:
        conn.close()
