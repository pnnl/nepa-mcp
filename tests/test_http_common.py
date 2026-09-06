"""Tests for shared JSON HTTP helpers."""

from __future__ import annotations

from typing import Any

import pytest
import requests

from nepa_mcp_common.http import UpstreamServiceError, get_json_rows, post_json


class _Response:
    def __init__(self, payload: Any = None, *, json_error: bool = False):
        self.payload = payload
        self.json_error = json_error

    def raise_for_status(self) -> None:
        return None

    def json(self):
        if self.json_error:
            raise ValueError("not json")
        return self.payload


def test_post_json_sends_json_body_and_returns_object(monkeypatch):
    observed = {}

    def fake_post(url, *, json, timeout):
        observed.update({"url": url, "json": json, "timeout": timeout})
        return _Response({"Table": [["value"], ["ok"]]})

    monkeypatch.setattr(requests, "post", fake_post)

    result = post_json(
        "https://example.test/query",
        json_body={"query": "SELECT 1"},
        timeout=12,
        service_name="Example",
    )

    assert result["Table"][1] == ["ok"]
    assert observed == {
        "url": "https://example.test/query",
        "json": {"query": "SELECT 1"},
        "timeout": 12,
    }


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (_Response(json_error=True), "invalid JSON"),
        (_Response(["not", "an", "object"]), "unexpected JSON type"),
        (_Response({"error": "bad query"}), "returned an error"),
    ],
)
def test_post_json_rejects_invalid_payloads(monkeypatch, response, message):
    monkeypatch.setattr(requests, "post", lambda *_a, **_k: response)

    with pytest.raises(UpstreamServiceError, match=message):
        post_json("https://example.test/query", json_body={"query": "SELECT 1"})


def test_post_json_wraps_request_errors(monkeypatch):
    def fail(*_args, **_kwargs):
        raise requests.Timeout("timeout detail")

    monkeypatch.setattr(requests, "post", fail)

    with pytest.raises(UpstreamServiceError, match="Example request failed"):
        post_json("https://example.test/query", json_body={}, service_name="Example")


@pytest.mark.parametrize("payload", [[], [{"id": "1", "missing": None, "complete": False}]])
def test_get_json_rows_preserves_arrays_and_values(monkeypatch, payload):
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: _Response(payload))
    assert get_json_rows("https://example.test/rows") == payload


@pytest.mark.parametrize(
    "response",
    [
        _Response(json_error=True),
        _Response({}),
        _Response({"error": True, "message": "invalid query"}),
        _Response([None]),
        _Response(["row"]),
        _Response("html"),
    ],
)
def test_get_json_rows_rejects_errors_and_malformed_payloads(monkeypatch, response):
    monkeypatch.setattr(requests, "get", lambda *_a, **_k: response)
    with pytest.raises(UpstreamServiceError):
        get_json_rows("https://example.test/rows")


@pytest.mark.parametrize(
    "error",
    [requests.Timeout("timeout"), requests.HTTPError("429 rate limited"), requests.HTTPError("503 unavailable")],
)
def test_get_json_rows_wraps_transport_failures(monkeypatch, error):
    def fail(*_a, **_k):
        raise error

    monkeypatch.setattr(requests, "get", fail)
    with pytest.raises(UpstreamServiceError, match="request failed"):
        get_json_rows("https://example.test/rows")
