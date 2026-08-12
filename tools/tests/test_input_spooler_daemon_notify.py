"""Tests for InputSpooler daemon HTTP notification."""

from unittest.mock import AsyncMock, patch

import pytest
from mypai_tools.input_spooler import InputSpooler


@pytest.mark.asyncio
async def test_input_spooler_notify_daemon(tmp_path) -> None:
    spooler = InputSpooler(inbox=tmp_path)

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value.status_code = 200

        await spooler.notify_daemon(
            title="Meeting Audio",
            filename="meeting.wav",
            transcript="Summary of project discussion",
            item_hash="abc123hash",
        )

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert "api/v1/session/prompt" in args[0]
        json_data = kwargs["json"]
        assert json_data["mode"] == "prompt"
        assert json_data["source"] == "spooler"
        assert "meeting.wav" in json_data["prompt"]
