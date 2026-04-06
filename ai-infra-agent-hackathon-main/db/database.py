"""
db/database.py — PostgreSQL connection and schema initialisation.
Owner: Person 3
Status: IMPLEMENTED (Epic 14)

Connection string read from CHAT_DB_URL env var.
Default: postgresql://localhost:5432/ai_advisor

Tables are created automatically on first run via init_db().
All functions are safe to call when Postgres is unavailable — they return
None/False and log a warning rather than raising.

Scan result caching has moved to Redis (cache/redis_cache.py).
The scan_cache, scan_cache_at, scan_region columns are no longer used.
"""

import logging
import os

logger = logging.getLogger(__name__)

_DEFAULT_DB_URL = "postgresql://localhost:5432/ai_advisor"

_CREATE_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS chat_sessions (
    id         TEXT PRIMARY KEY,
    region     TEXT NOT NULL,
    name       TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);
"""

_CREATE_MESSAGES_TABLE = """
CREATE TABLE IF NOT EXISTS chat_messages (
    id         SERIAL PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT NOW()
);
"""

_CREATE_MESSAGES_INDEX = """
CREATE INDEX IF NOT EXISTS idx_messages_session_id ON chat_messages(session_id);
"""


def get_db_url() -> str:
    return os.environ.get("CHAT_DB_URL", _DEFAULT_DB_URL)


def get_connection():
    """
    Return a psycopg2 connection to the configured PostgreSQL database.
    Returns None if the connection cannot be established.
    Never raises.
    """
    try:
        import psycopg2
        conn = psycopg2.connect(get_db_url())
        return conn
    except Exception as exc:
        logger.warning("PostgreSQL unavailable: %s — falling back to in-memory", exc)
        return None


def init_db() -> bool:
    """
    Create the chat_sessions and chat_messages tables if they don't exist.
    Returns True on success, False if Postgres is unreachable or any error occurs.
    Safe to call multiple times (idempotent).
    """
    conn = get_connection()
    if conn is None:
        return False
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(_CREATE_SESSIONS_TABLE)
                cur.execute(_CREATE_MESSAGES_TABLE)
                cur.execute(_CREATE_MESSAGES_INDEX)
        logger.info("Database initialised successfully")
        return True
    except Exception as exc:
        logger.warning("Failed to initialise database: %s", exc)
        return False
    finally:
        conn.close()

