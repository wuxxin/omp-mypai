"""Comprehensive unit tests for executors, input_spooler audio/hindsight APIs, and signal_client error handling."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mypai_tools.executors.http_executor import execute_http_job
from mypai_tools.executors.omp_rpc_executor import execute_omp_rpc_job
from mypai_tools.executors.python_executor import execute_python_job
from mypai_tools.input_spooler import InputSpooler
from mypai_tools.signal_client import SignalClient


# Helper to build mock httpx response
def make_mock_response(
    status_code: int = 200, text: str = '{"status": "ok"}', json_val: dict | None = None
):
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.text = text
    mock_resp.json.return_value = json_val if json_val is not None else {"status": "ok"}
    return mock_resp


# 1. HTTP Executor Tests
@pytest.mark.asyncio
async def test_http_executor_get_and_post() -> None:
    job_get = {
        "id": "http_1",
        "name": "HTTP Get Test",
        "kind": "http",
        "action": "GET",
        "args": ["http://example.com/api/test"],
        "result_prompt": "Result was: #[_RESULT]",
    }

    mock_resp = make_mock_response(status_code=200, text='{"status": "ok"}')

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp

        res = await execute_http_job(job_get)
        assert res["return_code"] == 0
        assert "status" in res["output"]


@pytest.mark.asyncio
async def test_http_executor_error_handling() -> None:
    job_err = {
        "id": "http_2",
        "name": "HTTP Error Test",
        "kind": "http",
        "action": "POST",
        "args": ["http://example.com/api/fail"],
        "result_error_prompt": "Failed with code: #[_RETURNCODE]",
    }

    mock_resp = make_mock_response(status_code=500, text="Internal Server Error")

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp

        res = await execute_http_job(job_err)
        assert res["return_code"] == 500


# 2. OMP RPC Executor Tests
@pytest.mark.asyncio
async def test_omp_rpc_executor_verbs() -> None:
    from mypai_tools.daemon.queue import TurnQueue

    queue = TurnQueue()

    # Prompt action
    res_prompt = await execute_omp_rpc_job(
        {"name": "RPC Prompt", "action": "prompt", "kwargs": {"prompt": "Hello RPC"}},
        daemon_queue=queue,
    )
    assert res_prompt["return_code"] == 0
    assert res_prompt["status"] == "queued"
    assert queue.depth() == 1

    # Steer action
    res_steer = await execute_omp_rpc_job(
        {"name": "RPC Steer", "action": "steer", "kwargs": {"prompt": "Steer Prompt"}},
        daemon_queue=queue,
    )
    assert res_steer["return_code"] == 0
    assert res_steer["status"] == "queued"
    assert queue.depth() == 2

    # Followup action
    res_followup = await execute_omp_rpc_job(
        {"name": "RPC Followup", "action": "followup", "args": ["Followup Prompt"]},
        daemon_queue=queue,
    )
    assert res_followup["return_code"] == 0
    assert res_followup["status"] == "queued"
    assert queue.depth() == 3


# 3. Python Executor Tests
@pytest.mark.asyncio
async def test_python_executor_lambda_and_code() -> None:
    # Lambda job
    job_lambda = {
        "name": "Py Lambda",
        "kind": "python",
        "action": "lambda args, kwargs: args[0] + kwargs['val']",
        "args": [10],
        "kwargs": {"val": 20},
    }
    res_lambda = await execute_python_job(job_lambda)
    assert res_lambda["return_code"] == 0
    assert res_lambda["output"] == "30"

    # Multi-line python code block
    job_code = {
        "name": "Py Code Block",
        "kind": "python",
        "action": "def run():\n    return 'Code Block Output'\nresult = run()",
    }
    res_code = await execute_python_job(job_code)
    assert res_code["return_code"] == 0
    assert "Code Block Output" in res_code["output"]


@pytest.mark.asyncio
async def test_python_executor_exception() -> None:
    job_err = {
        "name": "Py Error",
        "kind": "python",
        "action": "raise ValueError('Custom error')",
    }
    res_err = await execute_python_job(job_err)
    assert res_err["return_code"] == 1
    assert "Custom error" in res_err["error"] or "Custom error" in res_err["output"]


# 4. InputSpooler Audio STT & Hindsight Memory Tests
@pytest.mark.asyncio
async def test_spooler_transcribe_audio(tmp_path) -> None:
    spooler = InputSpooler(inbox=tmp_path)
    audio_file = tmp_path / "voice_memo.mp3"
    audio_file.write_bytes(b"FakeAudioData")

    mock_resp = make_mock_response(status_code=200, json_val={"text": "Transcribed voice audio."})

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp

        text = await spooler.transcribe_audio(audio_file)
        assert text == "Transcribed voice audio."


@pytest.mark.asyncio
async def test_spooler_retain_hindsight(tmp_path) -> None:
    spooler = InputSpooler(inbox=tmp_path, bank_id="test_bank")

    mock_resp_success = make_mock_response(status_code=200, json_val={"status": "retained"})

    # Primary /retain endpoint success
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_resp_success

        res = await spooler.retain_hindsight(
            title="Note",
            item_type="document",
            item_hash="123456",
            filename="note.txt",
            transcript="Important notes",
        )
        assert res["status"] == "success"


# 5. SignalClient HTTP Error Exception Handling
def test_signal_client_http_exceptions() -> None:
    client = SignalClient()

    with patch("urllib.request.urlopen") as mock_open:
        import urllib.error

        mock_open.side_effect = urllib.error.HTTPError(
            url="http://localhost/v1/test",
            code=403,
            msg="Forbidden",
            hdrs={},
            fp=None,
        )

        res = client._http_request("v1/test")
        assert "error" in res
        assert "HTTP 403" in res["error"]


@pytest.mark.asyncio
async def test_internal_vars_substitution_in_result_prompts() -> None:
    """Verify strictly _UPPERCASE internal variables expand in result_prompt templates."""
    job = {
        "name": "Var Substitution Test",
        "kind": "python",
        "action": "print('hello')",
        "args": ["arg1", "arg2"],
        "kwargs": {"key": "value"},
        "opts": {"timeout": 10},
        "result_prompt": "Action: #[_ACTION] | Args: #[_ARGS] | Kwargs: #[_KWARGS] | Opts: #[_OPTS] | Out: #[_OUTPUT]",
    }

    res = await execute_python_job(job)
    assert res["status"] == "success"
    assert "Action: print('hello')" in res["output"]
    assert 'Args: ["arg1", "arg2"]' in res["output"]
    assert 'Kwargs: {"key": "value"}' in res["output"]
    assert 'Opts: {"timeout": 10}' in res["output"]
