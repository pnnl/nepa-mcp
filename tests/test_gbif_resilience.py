"""
Resilience tests for the GBIF API layer.

Verify graceful behavior when the upstream GBIF REST API errors, times out, is
rate-limited, or returns malformed payloads, and when the counties ArcGIS
service fails. The GBIF layer is designed to degrade to partial/empty results
rather than raise on network failure (retries then returns what it has).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "gbif"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_gbif_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "_gbif_resilience_api", SERVER_DIR / "src" / "apis" / "gbif_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_gbif_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVER_DIR))


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.exceptions.HTTPError(f"status {self.status_code}")

    def json(self):
        return self._payload


def _no_sleep(api, monkeypatch):
    """Avoid real backoff/rate-limit sleeps during tests."""
    monkeypatch.setattr(api.time, "sleep", lambda *_a, **_k: None)


def _patch_counties(api, monkeypatch, features=None, query_fn=None):
    counties_mod = sys.modules["src.apis.counties_api"]
    monkeypatch.setattr(
        counties_mod.ArcGISService, "create_roi_buffer", staticmethod(lambda *_a, **_k: SIMPLE_GEOMETRY)
    )
    if query_fn is not None:
        monkeypatch.setattr(counties_mod.ArcGISService, "query_features", staticmethod(query_fn))
    else:
        monkeypatch.setattr(
            counties_mod.ArcGISService,
            "query_features",
            staticmethod(lambda *_a, **_k: ArcGISFeatureQueryResult(features=features or [], warnings=[])),
        )


class TestUpstreamGbifFailure:
    def test_connection_error_returns_partial_empty(self, monkeypatch):
        api = _load_gbif_api()
        _no_sleep(api, monkeypatch)
        import requests as req

        def boom(*_a, **_k):
            raise req.exceptions.ConnectionError("connection reset")

        monkeypatch.setattr(api.requests, "get", boom)
        # gbif_api swallows RequestException after retries and returns what it has.
        result = api.get_gbif_occurrences_in_roi(34.5, -106.5, 25.0)
        assert result["count"] == 0

    def test_timeout_returns_partial_empty(self, monkeypatch):
        api = _load_gbif_api()
        _no_sleep(api, monkeypatch)
        import requests as req

        def timeout(*_a, **_k):
            raise req.exceptions.Timeout("timed out")

        monkeypatch.setattr(api.requests, "get", timeout)
        result = api.get_gbif_occurrences_in_roi(34.5, -106.5, 25.0)
        assert result["count"] == 0

    def test_http_500_returns_partial_empty(self, monkeypatch):
        api = _load_gbif_api()
        _no_sleep(api, monkeypatch)
        monkeypatch.setattr(api.requests, "get", lambda *_a, **_k: _FakeResponse({}, status_code=500))
        result = api.get_gbif_occurrences_in_roi(34.5, -106.5, 25.0)
        assert result["count"] == 0

    def test_rate_limit_429_then_success(self, monkeypatch):
        api = _load_gbif_api()
        _no_sleep(api, monkeypatch)
        calls = {"n": 0}

        def flaky(url, params=None, timeout=None):
            calls["n"] += 1
            if calls["n"] == 1:
                return _FakeResponse({}, status_code=429)
            return _FakeResponse(
                {
                    "results": [{"key": 1, "scientificName": "Sp A", "iucnRedListCategory": "EN", "eventDate": ""}],
                    "endOfRecords": True,
                }
            )

        monkeypatch.setattr(api.requests, "get", flaky)
        result = api.get_gbif_occurrences_in_roi(34.5, -106.5, 25.0)
        assert result["count"] == 1
        assert calls["n"] >= 2

    def test_persistent_429_returns_partial_empty(self, monkeypatch):
        api = _load_gbif_api()
        _no_sleep(api, monkeypatch)
        monkeypatch.setattr(api.requests, "get", lambda *_a, **_k: _FakeResponse({}, status_code=429))
        result = api.get_gbif_occurrences_in_roi(34.5, -106.5, 25.0)
        assert result["count"] == 0


class TestMalformedPayloads:
    def test_missing_results_key(self, monkeypatch):
        api = _load_gbif_api()
        _no_sleep(api, monkeypatch)
        monkeypatch.setattr(api.requests, "get", lambda *_a, **_k: _FakeResponse({"endOfRecords": True}))
        result = api.get_gbif_occurrences_in_roi(34.5, -106.5, 25.0)
        assert result["count"] == 0

    def test_record_with_missing_fields_parses(self, monkeypatch):
        api = _load_gbif_api()
        _no_sleep(api, monkeypatch)
        monkeypatch.setattr(
            api.requests,
            "get",
            lambda *_a, **_k: _FakeResponse({"results": [{}], "endOfRecords": True}),
        )
        result = api.get_gbif_occurrences_in_roi(34.5, -106.5, 25.0)
        assert result["count"] == 1
        assert result["occurrences"][0]["scientific_name"] == "Unknown"


class TestCountiesUpstreamFailure:
    def test_counties_arcgis_failure_bubbles_up(self, monkeypatch):
        api = _load_gbif_api()
        _no_sleep(api, monkeypatch)

        def boom(*_a, **_k):
            raise RuntimeError("TIGERweb counties upstream 500")

        _patch_counties(api, monkeypatch, query_fn=boom)
        with pytest.raises(RuntimeError):
            api.get_gbif_species_by_county_sync(34.5, -118.0, 25.0)

    def test_per_county_gbif_failure_is_isolated(self, monkeypatch):
        """A GBIF failure for one county degrades to empty species, not a crash."""
        api = _load_gbif_api()
        _no_sleep(api, monkeypatch)
        _patch_counties(
            api,
            monkeypatch,
            features=[
                {"attributes": {"NAME": "LA County", "STATE": "06", "BASENAME": "Los Angeles", "GEOID": "06037"}}
            ],
        )
        import requests as req

        monkeypatch.setattr(api.requests, "get", lambda *_a, **_k: (_ for _ in ()).throw(req.exceptions.Timeout("t")))
        result = api.get_gbif_species_by_county_sync(34.5, -118.0, 25.0)
        # County is still present, just with zero species.
        assert result["total_counties"] == 1
        assert result["counties"][0]["total_species"] == 0
