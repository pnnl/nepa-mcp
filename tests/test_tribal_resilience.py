"""
Resilience tests for the tribal API layer.

Verify graceful behavior when the upstream ArcGIS service errors, returns
warnings, or returns malformed/empty payloads. Unlike some servers, the tribal
API catches per-layer query exceptions and converts them into warnings rather
than propagating them, so a single failing layer degrades gracefully.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_tribal_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "tribal"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_tribal_resilience_api", server_dir / "src" / "apis" / "tribal_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_tribal_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


class TestUpstreamQueryFailure:
    def test_all_layers_failing_reports_warning_not_error(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)

        def boom(*_a, **_k):
            raise RuntimeError("TIGERweb AIANNHA upstream 500")

        monkeypatch.setattr(api.ArcGISService, "query_features", boom)
        # Per-layer exceptions are caught and turned into warnings; no raise.
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        assert result["total"] == 0
        assert result["tribal_lands"] == []
        # Each of the 6 layers logs a failure warning plus the "no layers" summary.
        assert any("layer query failed" in w for w in result["warnings"])
        assert any("not a no-hit finding" in w for w in result["warnings"])

    def test_timeout_is_caught_per_layer(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)

        import requests as req_mod

        def timeout(*_a, **_k):
            raise req_mod.exceptions.Timeout("timed out")

        monkeypatch.setattr(api.ArcGISService, "query_features", timeout)
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        assert result["total"] == 0
        assert any("layer query failed" in w for w in result["warnings"])

    def test_one_layer_failing_others_succeed(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)

        def query_features(url, _layer_id, _geometry, *, service_name=None, **_k):
            if "Hawaiian Home Lands" in (service_name or ""):
                raise RuntimeError("HHL layer down")
            if "Federal American Indian Reservations" in (service_name or ""):
                return ArcGISFeatureQueryResult(features=[{"attributes": {"NAME": "Fed Res"}}], warnings=[])
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        # The healthy layer still returns data; the failed one becomes a warning.
        assert result["total"] == 1
        assert result["tribal_lands"][0]["name"] == "Fed Res"
        assert any("Hawaiian Home Lands layer query failed" in w for w in result["warnings"])


class TestDegradedButUsable:
    def test_warnings_are_carried_through(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)

        def query_features(url, _layer_id, _geometry, *, service_name=None, **_k):
            if "Federal American Indian Reservations" in (service_name or ""):
                return ArcGISFeatureQueryResult(
                    features=[{"attributes": {"NAME": "Fed Res"}}],
                    warnings=["reached the feature safety cap; results are partial."],
                    truncated=True,
                )
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        assert result["total"] == 1
        assert any("safety cap" in w for w in result["warnings"])

    def test_empty_features_is_not_an_error(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[], warnings=[]),
        )
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        assert result["total"] == 0
        assert result["tribal_lands"] == []
        # All layers queried successfully with zero hits: no "unavailable" warning.
        assert not any("not a no-hit finding" in w for w in result["warnings"])


class TestMalformedFeatures:
    def test_feature_without_attributes_key(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[{}], warnings=[]),
        )
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        # Six layers each returning one empty-attribute feature -> six "Unknown" records.
        assert result["total"] == len(api.TRIBAL_LAYERS)
        assert all(land["name"] == "Unknown" for land in result["tribal_lands"])

    def test_null_attribute_values_do_not_crash(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(
                features=[{"attributes": {"NAME": None, "AREALAND": None, "CENTLAT": None}}],
                warnings=[],
            ),
        )
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        assert result["total"] == len(api.TRIBAL_LAYERS)
        # NULL name sorts as "Unknown"; NULL area stays None.
        assert result["tribal_lands"][0]["area_sq_mi"] is None
