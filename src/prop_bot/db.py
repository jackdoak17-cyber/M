from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor

from src.prop_bot.config import get_settings

_POOL: SimpleConnectionPool | None = None


def _get_pool() -> SimpleConnectionPool:
    global _POOL
    if _POOL is None:
        settings = get_settings()
        if not settings.supabase_db_url:
            raise RuntimeError("SUPABASE_DB_URL is not set")
        _POOL = SimpleConnectionPool(1, 6, settings.supabase_db_url)
    return _POOL


@contextmanager
def db_cursor() -> Iterator[RealDictCursor]:
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = True
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
    finally:
        pool.putconn(conn)
