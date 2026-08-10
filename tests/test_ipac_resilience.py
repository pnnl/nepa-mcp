"""
Resilience tests for the IPaC API layer.

Verify graceful behavior when the upstream IPaC HTTP endpoint errors, times
out, returns malformed payloads, or returns an empty resources object. The
``requests.post`` call and the ArcGIS buffer layer are mocked to simulate each
failure mode. Note that ``ipac_api`` wraps ``requests`` exceptions and
``KeyError``/``ValueError`` in a generic ``Exception``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_ipac_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "ipac"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_ipac_resilience_api", server_dir / "src" / "apis" / "ipac_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_ipac_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


class _FakeResponse:
    def __init__(self, payload, status_code=200, json_exc=None):
        self._payload = payload
        self.status_code = status_code
        self._json_exc = json_exc

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests as req_mod

            raise req_mod.exceptions.HTTPError(f"status {self.status_code}")

    def json(self):
        if self._json_exc is not None:
            raise self._json_exc
        return self._payload


def _patch_geometry(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)
    monkeypatch.setattr(api.ArcGISService, "simplify_polygon_geometry", lambda *_a, **_k: SIMPLE_GEOMETRY)


class TestUpstreamRequestFailure:
    def test_timeout_is_wrapped(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)

        import requests as req_mod

        def timeout(*_a, **_k):
            raise req_mod.exceptions.Timeout("timed out")

        monkeypatch.setattr(api.requests, "post", timeout)
        with pytest.raises(Exception) as exc:
            api.get_ipac_resources_in_roi(34.5, -106.5)
        assert "IPaC API request failed" in str(exc.value)

    def test_connection_error_is_wrapped(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)

        import requests as req_mod

        def conn_err(*_a, **_k):
            raise req_mod.exceptions.ConnectionError("connection refused")

        monkeypatch.setattr(api.requests, "post", conn_err)
        with pytest.raises(Exception) as exc:
            api.get_ipac_resources_in_roi(34.5, -106.5)
        assert "IPaC API request failed" in str(exc.value)

    def test_http_error_status_is_wrapped(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        monkeypatch.setattr(api.requests, "post", lambda *_a, **_k: _FakeResponse({}, status_code=500))
        with pytest.raises(Exception) as exc:
            api.get_ipac_resources_in_roi(34.5, -106.5)
        assert "IPaC API request failed" in str(exc.value)


class TestMalformedPayload:
    def test_missing_resources_object_raises(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        # No "resources" key -> resources is None -> ValueError -> wrapped.
        monkeypatch.setattr(api.requests, "post", lambda *_a, **_k: _FakeResponse({"other": 1}))
        with pytest.raises(Exception) as exc:
            api.get_ipac_resources_in_roi(34.5, -106.5)
        assert "Error parsing IPaC response" in str(exc.value)

    def test_resources_not_a_dict_raises(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        monkeypatch.setattr(api.requests, "post", lambda *_a, **_k: _FakeResponse({"resources": []}))
        with pytest.raises(Exception) as exc:
            api.get_ipac_resources_in_roi(34.5, -106.5)
        assert "Error parsing IPaC response" in str(exc.value)

    def test_invalid_json_body_is_wrapped(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        monkeypatch.setattr(
            api.requests,
            "post",
            lambda *_a, **_k: _FakeResponse(None, json_exc=ValueError("No JSON object")),
        )
        with pytest.raises(Exception) as exc:
            api.get_ipac_resources_in_roi(34.5, -106.5)
        assert "Error parsing IPaC response" in str(exc.value)


class TestDegradedButUsable:
    def test_empty_resources_object_is_not_an_error(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        monkeypatch.setattr(api.requests, "post", lambda *_a, **_k: _FakeResponse({"resources": {}}))
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        assert result["species_count"] == 0
        assert result["migbirds_count"] == 0
        assert result["wetlands_count"] == 0
        assert result["critical_habitat_count"] == 0
        assert result["refuges_count"] == 0

    def test_partial_resources_parse_available_sections(self, monkeypatch):
        api = _load_ipac_api()
        _patch_geometry(api, monkeypatch)
        # Only migbirds present; other sections absent.
        partial = {
            "resources": {
                "migbirds": [
                    {
                        "phenologySpecies": {"commonName": "Bald Eagle"},
                        "level": {"name": "BCC"},
                    }
                ]
            }
        }
        monkeypatch.setattr(api.requests, "post", lambda *_a, **_k: _FakeResponse(partial))
        result = api.get_ipac_resources_in_roi(34.5, -106.5)
        assert result["migbirds_count"] == 1
        assert result["species_count"] == 0
