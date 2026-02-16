from datetime import datetime, timedelta, timezone

import arxiv
import pytest
import requests

from arxivc import client


@pytest.fixture(autouse=True)
def _reset_rate_limit(monkeypatch):
    monkeypatch.setattr(client, "_RATE_LIMIT_UNTIL", None)


def test_with_arxiv_client_maps_429_to_rate_limit_error():
    def op(_api_client):
        raise arxiv.HTTPError(url="https://example.test", retry=0, status=429)

    with pytest.raises(client.ArxivRateLimitError) as exc:
        client._with_arxiv_client(op)

    assert "HTTP 429" in str(exc.value)
    assert exc.value.retry_after_seconds >= 1


def test_with_arxiv_client_rejects_when_rate_limit_cooldown_is_active(monkeypatch):
    monkeypatch.setattr(
        client,
        "_RATE_LIMIT_UNTIL",
        datetime.now(timezone.utc) + timedelta(seconds=12),
    )
    called = {"value": False}

    def op(_api_client):
        called["value"] = True
        return []

    with pytest.raises(client.ArxivRateLimitError) as exc:
        client._with_arxiv_client(op)

    assert not called["value"]
    assert "temporarily rate limited" in str(exc.value)
    assert 1 <= exc.value.retry_after_seconds <= 12


def test_with_arxiv_client_maps_timeout_to_runtime_error():
    def op(_api_client):
        raise requests.exceptions.Timeout("socket timed out")

    with pytest.raises(RuntimeError) as exc:
        client._with_arxiv_client(op)

    assert "timed out" in str(exc.value)


def test_with_arxiv_client_maps_requests_exception_to_runtime_error():
    def op(_api_client):
        raise requests.exceptions.RequestException("dns failure")

    with pytest.raises(RuntimeError) as exc:
        client._with_arxiv_client(op)

    assert "arXiv request failed" in str(exc.value)
    assert "dns failure" in str(exc.value)


def test_rate_limit_status_reflects_active_cooldown(monkeypatch):
    monkeypatch.setattr(
        client,
        "_RATE_LIMIT_UNTIL",
        datetime.now(timezone.utc) + timedelta(seconds=9),
    )

    status = client.get_rate_limit_status()

    assert status["active"] is True
    assert 1 <= int(status["retry_after_seconds"]) <= 9
    assert isinstance(status["until"], str)


def test_clear_rate_limit_cooldown_resets_status(monkeypatch):
    monkeypatch.setattr(
        client,
        "_RATE_LIMIT_UNTIL",
        datetime.now(timezone.utc) + timedelta(seconds=4),
    )

    client.clear_rate_limit_cooldown()
    status = client.get_rate_limit_status()

    assert status["active"] is False
    assert status["retry_after_seconds"] == 0
