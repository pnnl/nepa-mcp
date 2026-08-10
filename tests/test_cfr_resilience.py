"""
Resilience tests for the CFR API layer.

Verify graceful behavior when the upstream eCFR / Federal Register HTTP APIs
error, time out, rate-limit (429 / empty 200 body), 404, or return malformed
payloads. The shared ``requests`` module is mocked to simulate each failure
mode. Because the CFR api layer has an internal retry/backoff loop
(``_cached_get``), these tests neutralize ``time.sleep`` to stay fast.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_cfr_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "cfr"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location("_cfr_resilience_api", server_dir / "src" / "apis" / "cfr_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_cfr_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


class _FakeResponse:
    def __init__(self, status_code=200, json_data=None, text=None):
        self.status_code = status_code
        self._json = {} if json_data is None else json_data
        self.text = text if text is not None else json.dumps(self._json)

    def json(self):
        if self._json is None:
            raise json.JSONDecodeError("no json", "", 0)
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests as _rq

            err = _rq.exceptions.HTTPError(f"HTTP {self.status_code}")
            err.response = self
            raise err


def _disable_cache(api, monkeypatch):
    monkeypatch.setattr(api, "_get_cached_response", lambda *_a, **_k: None)
    monkeypatch.setattr(api, "_cache_response", lambda *_a, **_k: None)
    monkeypatch.setattr(api.time, "sleep", lambda *_a, **_k: None)


class TestUpstreamFailure:
    def test_titles_returns_fallback_on_persistent_failure(self, monkeypatch):
        api = _load_cfr_api()
        _disable_cache(api, monkeypatch)

        def boom(*_a, **_k):
            raise api.requests.exceptions.ConnectionError("dns fail")

        monkeypatch.setattr(api.requests, "get", boom)
        # get_ecfr_titles is called with a fallback, so it degrades gracefully.
        titles = api.get_ecfr_titles()
        assert titles == {"titles": []}

    def test_versions_raises_api_error_without_fallback(self, monkeypatch):
        api = _load_cfr_api()
        _disable_cache(api, monkeypatch)

        def boom(*_a, **_k):
            raise api.requests.exceptions.ConnectionError("dns fail")

        monkeypatch.setattr(api.requests, "get", boom)
        cit = api.parse_cfr_citation("40 CFR 1502.14")
        with pytest.raises(api.CFRAPIError):
            api.get_section_versions(cit, start_date="2023-01-01", end_date="2023-12-31")

    def test_timeout_bubbles_to_api_error(self, monkeypatch):
        api = _load_cfr_api()
        _disable_cache(api, monkeypatch)

        def timeout(*_a, **_k):
            raise api.requests.exceptions.Timeout("timed out")

        monkeypatch.setattr(api.requests, "get", timeout)
        cit = api.parse_cfr_citation("40 CFR 1502.14")
        with pytest.raises(api.CFRAPIError):
            api.get_section_versions(cit, start_date="2023-01-01", end_date="2023-12-31")


class TestNotFound:
    def test_structure_404_raises_not_found(self, monkeypatch):
        api = _load_cfr_api()
        _disable_cache(api, monkeypatch)
        monkeypatch.setattr(api.requests, "get", lambda *_a, **_k: _FakeResponse(status_code=404))
        with pytest.raises(api.CFRNotFoundError):
            api.get_ecfr_title_structure(40, date="2026-01-01")

    def test_section_content_404_raises_not_found(self, monkeypatch):
        api = _load_cfr_api()
        _disable_cache(api, monkeypatch)
        monkeypatch.setattr(api.requests, "get", lambda *_a, **_k: _FakeResponse(status_code=404))
        cit = api.parse_cfr_citation("40 CFR 9999.99")
        with pytest.raises(api.CFRNotFoundError):
            api.get_ecfr_section_content(cit, date="2026-01-01")


class TestRateLimitRetry:
    def test_recovers_after_transient_500(self, monkeypatch):
        api = _load_cfr_api()
        _disable_cache(api, monkeypatch)
        calls = {"n": 0}

        def flaky(*_a, **_k):
            calls["n"] += 1
            if calls["n"] < 2:
                return _FakeResponse(status_code=500)
            return _FakeResponse(json_data={"content_versions": [{"date": "2023-01-01", "substantive": True}]})

        monkeypatch.setattr(api.requests, "get", flaky)
        cit = api.parse_cfr_citation("40 CFR 1502.14")
        events = api.get_section_versions(cit, start_date="2023-01-01", end_date="2023-12-31")
        assert len(events) == 1
        assert calls["n"] >= 2

    def test_empty_body_then_success(self, monkeypatch):
        api = _load_cfr_api()
        _disable_cache(api, monkeypatch)
        calls = {"n": 0}

        def flaky(*_a, **_k):
            calls["n"] += 1
            if calls["n"] < 2:
                return _FakeResponse(status_code=200, text="")
            return _FakeResponse(json_data={"content_versions": []})

        monkeypatch.setattr(api.requests, "get", flaky)
        cit = api.parse_cfr_citation("40 CFR 1502.14")
        events = api.get_section_versions(cit, start_date="2023-01-01", end_date="2023-12-31")
        assert events == []
        assert calls["n"] >= 2


class TestMalformedPayloads:
    def test_unparseable_html_returns_none(self, monkeypatch):
        api = _load_cfr_api()
        # _parse_section_html swallows parser errors and returns a dict; a truly
        # empty document still parses to an empty tree, not a crash.
        parsed = api._parse_section_html("<not valid <<< html")
        assert parsed is None or isinstance(parsed, dict)

    def test_empty_html_yields_empty_tree(self, monkeypatch):
        api = _load_cfr_api()
        parsed = api._parse_section_html("")
        assert isinstance(parsed, dict)
        assert parsed["paragraphs"] == []

    def test_versions_missing_key_yields_empty(self, monkeypatch):
        api = _load_cfr_api()
        _disable_cache(api, monkeypatch)
        # extract_key='content_versions' absent -> default [].
        monkeypatch.setattr(api.requests, "get", lambda *_a, **_k: _FakeResponse(json_data={"unexpected": 1}))
        cit = api.parse_cfr_citation("40 CFR 1502.14")
        events = api.get_section_versions(cit, start_date="2023-01-01", end_date="2023-12-31")
        assert events == []


class TestAncestryDegradation:
    def test_partless_citation_returns_empty_ancestry(self, monkeypatch):
        api = _load_cfr_api()
        cit = api.parse_cfr_citation("title 50")
        # No part -> the api short-circuits with [] and never calls HTTP.
        assert api.get_section_ancestry(cit) == []
