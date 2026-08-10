"""
Resilience tests for the tigerweb_counties API layer.

Verify graceful (or documented) behavior when the upstream Census TIGERweb
service errors, times out, returns malformed payloads, or truncates results.

These tests assert the ACTUAL current behavior of the source, not a desired
behavior. In particular:

* A successful HTTP response whose ``features`` key is ``null`` is coerced to an
  empty list by ``ArcGISService.query_features`` (``payload.get("features") or []``),
  so the API returns zero counties gracefully -- it does NOT crash.
* A network / HTTP error is wrapped by ``ArcGISService.query_features`` into a
  ``RuntimeError`` and bubbles up through ``get_counties_in_roi`` -- it does NOT
  return empty.
* If ``query_features`` itself yields ``features=None`` (not possible via the
  real HTTP path, but asserted here for the API layer contract), the county loop
  raises ``TypeError`` because it iterates ``result.features`` directly.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = ROOT / "tigerweb_counties"
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_counties_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    sys.path.insert(0, str(SERVER_DIR))
    try:
        spec = importlib.util.spec_from_file_location(
            "_counties_resilience_api", SERVER_DIR / "src" / "apis" / "counties_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_counties_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SERVER_DIR))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


# ---------------------------------------------------------------------------
# (a) Successful response whose "features" key is null.
# The real HTTP path runs through ArcGISService.query_features, which coerces a
# null "features" to [] -> the API returns zero counties gracefully.
# ---------------------------------------------------------------------------


class TestNullFeaturesResponse:
    def test_null_features_returns_empty_not_crash(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)

        import requests

        monkeypatch.setattr(requests, "post", lambda *_a, **_k: _FakeResponse({"features": None}))
        result = api.get_counties_in_roi(34.5, -106.5)
        assert result["total_counties"] == 0
        assert result["counties"] == []

    def test_missing_features_key_returns_empty(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)

        import requests

        monkeypatch.setattr(requests, "post", lambda *_a, **_k: _FakeResponse({}))
        result = api.get_counties_in_roi(34.5, -106.5)
        assert result["total_counties"] == 0


# ---------------------------------------------------------------------------
# (b) Network / HTTP error.
# ArcGISService.query_features wraps requests.RequestException into a
# RuntimeError, which propagates out of get_counties_in_roi (does NOT swallow).
# ---------------------------------------------------------------------------


class TestUpstreamNetworkFailure:
    def test_http_error_bubbles_up_as_runtimeerror(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)

        import requests

        def boom(*_a, **_k):
            raise requests.exceptions.HTTPError("500 server error")

        monkeypatch.setattr(requests, "post", boom)
        with pytest.raises(RuntimeError):
            api.get_counties_in_roi(34.5, -106.5)

    def test_connection_error_bubbles_up_as_runtimeerror(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)

        import requests

        def boom(*_a, **_k):
            raise requests.exceptions.ConnectionError("connection refused")

        monkeypatch.setattr(requests, "post", boom)
        with pytest.raises(RuntimeError):
            api.get_counties_in_roi(34.5, -106.5)

    def test_timeout_bubbles_up_as_runtimeerror(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)

        import requests

        def boom(*_a, **_k):
            raise requests.exceptions.Timeout("timed out")

        monkeypatch.setattr(requests, "post", boom)
        with pytest.raises(RuntimeError):
            api.get_counties_in_roi(34.5, -106.5)

    def test_arcgis_error_payload_bubbles_up(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)

        import requests

        monkeypatch.setattr(
            requests,
            "post",
            lambda *_a, **_k: _FakeResponse({"error": {"message": "Invalid query"}}),
        )
        with pytest.raises(RuntimeError):
            api.get_counties_in_roi(34.5, -106.5)


# ---------------------------------------------------------------------------
# Degraded but usable
# ---------------------------------------------------------------------------


class TestDegradedButUsable:
    def test_warnings_are_carried_through(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(
                features=[{"attributes": {"NAME": "Bernalillo County", "STATE": "35"}}],
                warnings=["reached the feature safety cap; results are partial."],
                truncated=True,
            ),
        )
        result = api.get_counties_in_roi(34.5, -106.5)
        assert result["total_counties"] == 1
        assert any("safety cap" in w for w in result["warnings"])

    def test_empty_features_is_not_an_error(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[], warnings=[]),
        )
        result = api.get_counties_in_roi(34.5, -106.5)
        assert result["total_counties"] == 0
        assert result["counties"] == []


# ---------------------------------------------------------------------------
# Malformed features
# ---------------------------------------------------------------------------


class TestMalformedFeatures:
    def test_feature_without_attributes_key(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[{}], warnings=[]),
        )
        result = api.get_counties_in_roi(34.5, -106.5)
        assert result["total_counties"] == 1
        assert result["counties"][0]["name"] == "Unknown"

    def test_null_attribute_values_do_not_crash(self, monkeypatch):
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(
                features=[{"attributes": {"NAME": None, "STATE": None, "GEOID": None}}],
                warnings=[],
            ),
        )
        result = api.get_counties_in_roi(34.5, -106.5)
        assert result["total_counties"] == 1

    def test_query_features_returning_none_features_raises_typeerror(self, monkeypatch):
        # Documents the API-layer contract: the county loop iterates
        # result.features directly, so a None features list raises TypeError.
        # (Not reachable via the real HTTP path, which coerces null -> [].)
        api = _load_counties_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=None, warnings=[]),
        )
        with pytest.raises(TypeError):
            api.get_counties_in_roi(34.5, -106.5)
