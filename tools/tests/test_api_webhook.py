"""Tests for Signal Webhook endpoint and whitelist filtering."""

def test_signal_webhook_authorized_sender(test_client) -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+15559992222",
            "timestamp": 1723420000000,
            "dataMessage": {"message": "Test whitelisted message"},
        }
    }
    res = test_client.post("/api/v1/signal/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "acknowledged"
    assert data["sender"] == "+15559992222"


def test_signal_webhook_unauthorized_sender(test_client) -> None:
    payload = {
        "envelope": {
            "sourceNumber": "+19990000000",  # Unauthorized number
            "timestamp": 1723420000000,
            "dataMessage": {"message": "Spam message"},
        }
    }
    res = test_client.post("/api/v1/signal/webhook", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ignored_unauthorized"
