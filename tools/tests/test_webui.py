"""Tests for WebUI static endpoints."""

def test_webui_ui_endpoint(test_client) -> None:
    res = test_client.get("/ui")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "myPAI Console" in res.text


def test_webui_root_endpoint(test_client) -> None:
    res = test_client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    assert "myPAI Console" in res.text

