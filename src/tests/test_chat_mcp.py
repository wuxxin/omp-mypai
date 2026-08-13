"""Unit tests for chat_mcp FastMCP tools."""

from unittest.mock import patch

from mypai_tools import chat_mcp


def test_chat_mcp_get_next_unread_message() -> None:
    expected = {
        "status": "success",
        "sender": "+15559992222",
        "message": "Test Message",
        "timestamp": 1723420000000,
        "attachments": [],
    }

    with patch.object(chat_mcp.client, "fetch_next_unread_message", return_value=expected) as mock_fetch:
        res = chat_mcp.get_next_unread_message(sender="+15559992222")
        assert res == expected
        mock_fetch.assert_called_once_with(sender="+15559992222")


def test_chat_mcp_send_signal_message() -> None:
    expected = {"status": "sent"}
    with patch.object(chat_mcp.client, "send_message", return_value=expected) as mock_send:
        res = chat_mcp.send_signal_message(recipient="+15559992222", message="Hi")
        assert res == expected
        mock_send.assert_called_once_with(recipient="+15559992222", text="Hi", attachments=None)


def test_chat_mcp_list_signal_chats() -> None:
    expected = {"chats": [{"number": "+15559992222", "name": "Alice"}]}
    with patch.object(chat_mcp.client, "list_chats", return_value=expected) as mock_list:
        res = chat_mcp.list_signal_chats()
        assert res == expected
        mock_list.assert_called_once()
