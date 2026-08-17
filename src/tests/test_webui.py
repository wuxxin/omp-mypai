"""Tests for WebUI static endpoints."""


def test_webui_ui_endpoint(test_client) -> None:
    res = test_client.get("/ui")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "myPAI Console:" in res.text
    assert "Main Agent:" in res.text
    assert "main-agent-badge" in res.text
    assert "team-header-badge" in res.text
    assert "agents-active-badge" in res.text
    assert "agents-streaming-badge" in res.text
    assert "cron-jobs-list" in res.text
    assert "team-running-tasks-list" in res.text
    assert "team-finished-tasks-list" in res.text
    assert "viewTaskOutput" in res.text
    assert "closeTaskViewer" in res.text


def test_webui_root_endpoint(test_client) -> None:
    res = test_client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "myPAI Console:" in res.text
