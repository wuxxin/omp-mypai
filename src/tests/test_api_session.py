"""Tests for mypai_daemon REST API session endpoints."""

def test_session_prompt_endpoint(test_client) -> None:
    res = test_client.post(
        "/api/v1/session/prompt",
        json={"prompt": "Test prompt text", "mode": "prompt", "source": "webui"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"
    assert "task_id" in data


def test_session_steer_endpoint(test_client) -> None:
    res = test_client.post(
        "/api/v1/session/steer",
        json={"prompt": "Interrupt task", "source": "webui"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"


def test_session_followup_endpoint(test_client) -> None:
    res = test_client.post(
        "/api/v1/session/followup",
        json={"prompt": "Append extra note", "source": "webui"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"


def test_session_abort_and_prompt_endpoint(test_client) -> None:
    res = test_client.post(
        "/api/v1/session/abort_and_prompt",
        json={"prompt": "Cancel and prompt new", "source": "webui"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "queued"


def test_session_status_endpoint(test_client) -> None:
    res = test_client.get("/api/v1/session/status")
    assert res.status_code == 200
    data = res.json()
    assert data["session_name"] == "mypai_daemon - running"
    assert data["version"] == "1.0.0"
    assert "uptime_sec" in data

