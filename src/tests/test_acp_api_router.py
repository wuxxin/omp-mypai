"""Integration tests for FastAPI ACP REST API router endpoints."""

import pytest
from fastapi.testclient import TestClient
from mypai_tools.daemon.api.app import app


@pytest.fixture
def client(tmp_path: pytest.TempPathFactory) -> TestClient:
    """Fixture providing FastAPI test client with mocked state."""
    app.state.agent_dir = str(tmp_path)
    return TestClient(app)


def test_acp_api_get_status(client: TestClient) -> None:
    """Test GET /api/v1/acp/status endpoint."""
    resp = client.get("/api/v1/acp/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["state"] == "running"
    assert data["running"] is True


def test_acp_api_suspend_and_enable(client: TestClient) -> None:
    """Test POST /api/v1/acp/suspend and /enable endpoints."""
    suspend_resp = client.post("/api/v1/acp/suspend")
    assert suspend_resp.status_code == 200
    assert suspend_resp.json()["state"] == "suspended"

    status_resp = client.get("/api/v1/acp/status")
    assert status_resp.json()["state"] == "suspended"

    enable_resp = client.post("/api/v1/acp/enable")
    assert enable_resp.status_code == 200
    assert enable_resp.json()["state"] == "running"
