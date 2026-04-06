"""
db/session_manager.py — Chat session and message CRUD operations.
Owner: Person 3
Status: IMPLEMENTED (Epic 14)

All functions are safe to call when Postgres is unavailable — they return
empty results or no-op rather than raising.
"""

import logging
import uuid
from datetime import datetime

from db.database import get_connection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Session naming
# ---------------------------------------------------------------------------

def generate_session_name(first_content: str, region: str, is_scan: bool) -> str:
    """
    Generate a display name for a chat session.

    is_scan=True  → "Infrastructure scan — {region} — {DD Mon}"
    is_scan=False → condensed first user message

    Always truncated to 40 characters with ellipsis if longer.
    """
    if is_scan:
        date_str = datetime.now().strftime("%d %b")
        name = f"Infrastructure scan — {region} — {date_str}"
    else:
        name = first_content.strip()

    if len(name) > 40:
        return name[:37] + "..."
    return name


# ---------------------------------------------------------------------------
# Session CRUD
# ---------------------------------------------------------------------------

def create_session(region: str) -> str:
    """
    Create a new chat session in the database.
    Returns the new session UUID string.
    Falls back to returning a UUID without DB insert if Postgres is unavailable.
    """
    session_id = str(uuid.uuid4())
    placeholder_name = f"New session — {region}"

    conn = get_connection()
    if conn is None:
        logger.warning("DB unavailable — session %s not persisted", session_id)
        return session_id

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO chat_sessions (id, region, name) VALUES (%s, %s, %s)",
                    (session_id, region, placeholder_name),
                )
        return session_id
    except Exception as exc:
        logger.warning("Failed to create session: %s", exc)
        return session_id
    finally:
        conn.close()


def list_sessions() -> list:
    """
    Return all sessions ordered by updated_at DESC.
    Each dict: {id, name, region, updated_at}
    Returns empty list if DB unavailable.
    """
    conn = get_connection()
    if conn is None:
        return []

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, region, updated_at FROM chat_sessions ORDER BY updated_at DESC"
            )
            rows = cur.fetchall()
        return [
            {"id": r[0], "name": r[1], "region": r[2], "updated_at": r[3]}
            for r in rows
        ]
    except Exception as exc:
        logger.warning("Failed to list sessions: %s", exc)
        return []
    finally:
        conn.close()


def delete_session(session_id: str) -> None:
    """
    Delete a session and all its messages (ON DELETE CASCADE handles messages).
    No-op if DB unavailable.
    """
    conn = get_connection()
    if conn is None:
        return

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM chat_sessions WHERE id = %s", (session_id,))
    except Exception as exc:
        logger.warning("Failed to delete session %s: %s", session_id, exc)
    finally:
        conn.close()


def update_session_name(session_id: str, name: str) -> None:
    """
    Update the display name of a session.
    No-op if DB unavailable.
    """
    conn = get_connection()
    if conn is None:
        return

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE chat_sessions SET name = %s, updated_at = NOW() WHERE id = %s",
                    (name, session_id),
                )
    except Exception as exc:
        logger.warning("Failed to update session name for %s: %s", session_id, exc)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Message CRUD
# ---------------------------------------------------------------------------

def save_message(session_id: str, role: str, content: str) -> None:
    """
    Insert a message row and bump the session's updated_at timestamp.
    No-op if DB unavailable.
    """
    conn = get_connection()
    if conn is None:
        return

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO chat_messages (session_id, role, content) VALUES (%s, %s, %s)",
                    (session_id, role, content),
                )
                cur.execute(
                    "UPDATE chat_sessions SET updated_at = NOW() WHERE id = %s",
                    (session_id,),
                )
    except Exception as exc:
        logger.warning("Failed to save message for session %s: %s", session_id, exc)
    finally:
        conn.close()


def load_messages(session_id: str) -> list:
    """
    Return all messages for a session ordered by created_at ASC.
    Each dict: {role, content}
    Returns empty list if DB unavailable.
    """
    conn = get_connection()
    if conn is None:
        return []

    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role, content FROM chat_messages WHERE session_id = %s ORDER BY created_at ASC",
                (session_id,),
            )
            rows = cur.fetchall()
        return [{"role": r[0], "content": r[1]} for r in rows]
    except Exception as exc:
        logger.warning("Failed to load messages for session %s: %s", session_id, exc)
        return []
    finally:
        conn.close()
