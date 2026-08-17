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
    assert "session_state" in data
    assert "status" in data


def test_session_state_endpoint(test_client) -> None:
    res = test_client.get("/api/v1/session/state")
    assert res.status_code == 200
    data = res.json()
    assert "session_id" in data
    assert "model" in data
    assert "context_usage" in data


def test_session_reconnect_endpoint(test_client) -> None:
    res = test_client.post("/api/v1/session/reconnect")
    assert res.status_code == 200
    data = res.json()
    assert "status" in data
    assert "connected" in data


def test_session_abort_control_plane_interrupt(test_client) -> None:
    # First queue a couple of turns
    test_client.post(
        "/api/v1/session/prompt",
        json={"prompt": "Turn 1 to be purged", "mode": "prompt", "source": "webui"},
    )
    test_client.post(
        "/api/v1/session/prompt",
        json={"prompt": "Turn 2 to be purged", "mode": "prompt", "source": "webui"},
    )

    # Trigger control-plane instant abort
    abort_res = test_client.post("/api/v1/session/abort")
    assert abort_res.status_code == 200
    abort_data = abort_res.json()
    assert abort_data["status"] == "aborted"
    assert "last_turn" in abort_data

    # Check status to verify queue depth was purged to 0
    status_res = test_client.get("/api/v1/session/status")
    status_data = status_res.json()
    assert status_data["queue_depth"] == 0
