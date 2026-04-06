"""
tests/test_session_manager.py — Unit tests for chat session management.
Owner: Person 3
Status: IMPLEMENTED (Epic 14)

DB-dependent functions are tested with mocked psycopg2 connections.
generate_session_name has no DB dependency and is tested directly.
"""

import pytest
from unittest.mock import MagicMock, patch
from db.session_manager import (
    generate_session_name,
    create_session,
    list_sessions,
    delete_session,
    update_session_name,
    save_message,
    load_messages,
)


# ---------------------------------------------------------------------------
# generate_session_name — no DB dependency
# ---------------------------------------------------------------------------

class TestGenerateSessionName:
    def test_scan_name_format(self):
        name = generate_session_name("anything", "us-east-1", is_scan=True)
        assert "Infrastructure scan" in name
        assert "us-east-1" in name

    def test_scan_name_contains_date(self):
        from datetime import datetime
        name = generate_session_name("anything", "us-east-1", is_scan=True)
        date_str = datetime.now().strftime("%d %b")
        assert date_str in name

    def test_user_message_name_uses_content(self):
        name = generate_session_name("Tell me about idle EC2", "us-east-1", is_scan=False)
        assert "Tell me about idle EC2" in name

    def test_truncation_at_40_chars(self):
        long_msg = "A" * 50
        name = generate_session_name(long_msg, "us-east-1", is_scan=False)
        assert len(name) == 40
        assert name.endswith("...")

    def test_exactly_40_chars_not_truncated(self):
        msg = "A" * 40
        name = generate_session_name(msg, "us-east-1", is_scan=False)
        assert len(name) == 40
        assert not name.endswith("...")

    def test_short_message_not_truncated(self):
        name = generate_session_name("Short message", "us-east-1", is_scan=False)
        assert name == "Short message"

    def test_scan_name_truncated_if_long_region(self):
        # Very long region name should still be truncated
        name = generate_session_name("x", "ap-southeast-very-long-region-name", is_scan=True)
        assert len(name) <= 40

    def test_whitespace_stripped_from_user_message(self):
        name = generate_session_name("  hello world  ", "us-east-1", is_scan=False)
        assert name == "hello world"


# ---------------------------------------------------------------------------
# DB functions — mocked psycopg2
# ---------------------------------------------------------------------------

def _make_mock_conn(fetchall_return=None):
    """Return a mock psycopg2 connection with a cursor that returns fetchall_return."""
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = fetchall_return or []
    mock_cursor.__enter__ = MagicMock(return_value=mock_cursor)
    mock_cursor.__exit__ = MagicMock(return_value=False)

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    return mock_conn, mock_cursor


class TestCreateSession:
    def test_returns_uuid_string(self):
        mock_conn, _ = _make_mock_conn()
        with patch("db.session_manager.get_connection", return_value=mock_conn):
            session_id = create_session("us-east-1")
        import uuid
        uuid.UUID(session_id)  # raises if not valid UUID

    def test_returns_uuid_when_db_unavailable(self):
        with patch("db.session_manager.get_connection", return_value=None):
            session_id = create_session("us-east-1")
        import uuid
        uuid.UUID(session_id)

    def test_inserts_into_db(self):
        mock_conn, mock_cursor = _make_mock_conn()
        with patch("db.session_manager.get_connection", return_value=mock_conn):
            create_session("eu-west-1")
        mock_cursor.execute.assert_called()
        call_args = mock_cursor.execute.call_args[0][0]
        assert "INSERT INTO chat_sessions" in call_args


class TestListSessions:
    def test_returns_list_of_dicts(self):
        rows = [("uuid-1", "Session 1", "us-east-1", "2024-01-01")]
        mock_conn, _ = _make_mock_conn(fetchall_return=rows)
        with patch("db.session_manager.get_connection", return_value=mock_conn):
            sessions = list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["id"] == "uuid-1"
        assert sessions[0]["name"] == "Session 1"
        assert sessions[0]["region"] == "us-east-1"

    def test_returns_empty_list_when_db_unavailable(self):
        with patch("db.session_manager.get_connection", return_value=None):
            sessions = list_sessions()
        assert sessions == []

    def test_returns_empty_list_on_no_rows(self):
        mock_conn, _ = _make_mock_conn(fetchall_return=[])
        with patch("db.session_manager.get_connection", return_value=mock_conn):
            sessions = list_sessions()
        assert sessions == []


class TestDeleteSession:
    def test_executes_delete(self):
        mock_conn, mock_cursor = _make_mock_conn()
        with patch("db.session_manager.get_connection", return_value=mock_conn):
            delete_session("uuid-1")
        mock_cursor.execute.assert_called()
        call_args = mock_cursor.execute.call_args[0][0]
        assert "DELETE FROM chat_sessions" in call_args

    def test_noop_when_db_unavailable(self):
        with patch("db.session_manager.get_connection", return_value=None):
            delete_session("uuid-1")  # should not raise


class TestUpdateSessionName:
    def test_executes_update(self):
        mock_conn, mock_cursor = _make_mock_conn()
        with patch("db.session_manager.get_connection", return_value=mock_conn):
            update_session_name("uuid-1", "New Name")
        mock_cursor.execute.assert_called()
        call_args = mock_cursor.execute.call_args[0][0]
        assert "UPDATE chat_sessions" in call_args

    def test_noop_when_db_unavailable(self):
        with patch("db.session_manager.get_connection", return_value=None):
            update_session_name("uuid-1", "Name")  # should not raise


class TestSaveMessage:
    def test_inserts_message_and_updates_session(self):
        mock_conn, mock_cursor = _make_mock_conn()
        with patch("db.session_manager.get_connection", return_value=mock_conn):
            save_message("uuid-1", "user", "Hello")
        assert mock_cursor.execute.call_count == 2
        first_call = mock_cursor.execute.call_args_list[0][0][0]
        assert "INSERT INTO chat_messages" in first_call

    def test_noop_when_db_unavailable(self):
        with patch("db.session_manager.get_connection", return_value=None):
            save_message("uuid-1", "user", "Hello")  # should not raise


class TestLoadMessages:
    def test_returns_list_of_role_content_dicts(self):
        rows = [("user", "Hello"), ("assistant", "Hi there")]
        mock_conn, _ = _make_mock_conn(fetchall_return=rows)
        with patch("db.session_manager.get_connection", return_value=mock_conn):
            messages = load_messages("uuid-1")
        assert len(messages) == 2
        assert messages[0] == {"role": "user", "content": "Hello"}
        assert messages[1] == {"role": "assistant", "content": "Hi there"}

    def test_returns_empty_list_when_db_unavailable(self):
        with patch("db.session_manager.get_connection", return_value=None):
            messages = load_messages("uuid-1")
        assert messages == []

    def test_returns_empty_list_on_no_rows(self):
        mock_conn, _ = _make_mock_conn(fetchall_return=[])
        with patch("db.session_manager.get_connection", return_value=mock_conn):
            messages = load_messages("uuid-1")
        assert messages == []

    def test_message_round_trip(self):
        """save then load returns same content (via mocked DB)."""
        saved = []

        mock_conn_save, mock_cursor_save = _make_mock_conn()
        with patch("db.session_manager.get_connection", return_value=mock_conn_save):
            save_message("uuid-1", "user", "Test message")
            saved.append(("user", "Test message"))

        rows = saved
        mock_conn_load, _ = _make_mock_conn(fetchall_return=rows)
        with patch("db.session_manager.get_connection", return_value=mock_conn_load):
            messages = load_messages("uuid-1")

        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "Test message"
