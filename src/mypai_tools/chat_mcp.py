#!/usr/bin/env python3
"""MCP tool server for Signal messaging integration using SignalClient SDK."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from mypai_tools.signal_client import SignalClient

mcp = FastMCP("chat-channel")
client = SignalClient()


@mcp.tool()
def get_next_unread_message(sender: str | None = None) -> dict[str, Any]:
    """Fetch the single oldest unread Signal message (FIFO order).
    
    Automatically dispatches a Read Receipt (two white checkmarks 🗸🗸) and Typing Indicator
    to the sender, extracts incoming attachments to local disk, and returns message details.
    
    Args:
        sender: Optional sender phone number to filter for. Defaults to SIGNAL_ALLOWED_SENDER.
    """
    return client.fetch_next_unread_message(sender=sender)


@mcp.tool()
def send_signal_message(
    recipient: str | None = None,
    message: str = "",
    attachments: list[str] | None = None,
) -> dict[str, Any]:
    """Send an outbound message via Signal to a recipient phone number or group ID.
    
    Args:
        recipient: Target recipient phone number. Defaults to SIGNAL_ALLOWED_SENDER if omitted.
        message: Text message body.
        attachments: Optional list of local file paths (e.g. ['scratch/chart.png']).
    """
    return client.send_message(recipient=recipient, text=message, attachments=attachments)


@mcp.tool()
def list_signal_chats() -> dict[str, Any]:
    """List registered Signal contacts and group IDs."""
    return client.list_chats()


if __name__ == "__main__":
    mcp.run(transport="stdio")
