"""Tests for SignalClient SDK."""

from mypai_tools.signal_client import SignalClient


def test_signal_client_whitelist_check() -> None:
    client = SignalClient(
        account="+15550001111",
        allowed_sender="+15559992222",
    )

    assert client.is_sender_allowed("+15559992222") is True
    assert client.is_sender_allowed("15559992222") is True
    assert client.is_sender_allowed("+19998887777") is False
