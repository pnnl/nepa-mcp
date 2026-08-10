"""
Resilience tests for the BLM API layer.

Verify graceful behavior when the upstream ArcGIS service errors, times out,
returns malformed payloads, or truncates results. The shared ArcGISService is
mocked to simulate each failure mode.

Note: the BLM ``_query_blm_*`` helpers catch upstream query exceptions and
convert them into a ``warnings`` entry (returning empty results), so query
failures degrade gracefully rather than bubbling up. Failures in
``create_roi_buffer`` (which runs outside the try/except) do bubble up.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-112.0, 38.0], [-111.0, 38.0], [-111.0, 39.0], [-112.0, 39.0], [-112.0, 38.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_blm_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "blm"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location("_blm_resilience_api", server_dir / "src" / "apis" / "blm_api.py")
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_blm_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


class TestUpstreamQueryFailure:
    def test_query_error_is_captured_as_warning(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)

        def boom(*_a, **_k):
            raise RuntimeError("BLM land use plans upstream 500")

        monkeypatch.setattr(api.ArcGISService, "query_features", boom)
        result = api.get_blm_land_use_plans_in_roi(38.5, -111.5)
        # Query failures are caught and surfaced as warnings, not raised.
        assert result["total"] == 0
        assert result["land_use_plans"] == []
        assert any("failed" in w.lower() for w in result["warnings"])

    def test_timeout_is_captured_as_warning(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)

        import requests as req_mod

        def timeout(*_a, **_k):
            raise req_mod.exceptions.Timeout("timed out")

        monkeypatch.setattr(api.ArcGISService, "query_features", timeout)
        result = api.get_blm_wilderness_areas_in_roi(38.5, -111.5)
        assert result["total"] == 0
        assert any("failed" in w.lower() for w in result["warnings"])

    def test_roi_buffer_failure_bubbles_up(self, monkeypatch):
        api = _load_blm_api()

        def boom(*_a, **_k):
            raise RuntimeError("ROI buffer service down")

        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", boom)
        with pytest.raises(RuntimeError):
            api.get_blm_national_monuments_in_roi(38.5, -111.5)


class TestDegradedButUsable:
    def test_warnings_are_carried_through(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)

        def query_features(*_a, **_k):
            return ArcGISFeatureQueryResult(
                features=[{"attributes": {"LUPName": "Grand Staircase RMP"}}],
                warnings=["reached the feature safety cap; results are partial."],
                truncated=True,
            )

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_blm_land_use_plans_in_roi(38.5, -111.5)
        assert result["total"] == 1
        assert any("safety cap" in w for w in result["warnings"])

    def test_empty_features_is_not_an_error(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[], warnings=[]),
        )
        result = api.get_blm_wilderness_areas_in_roi(38.5, -111.5)
        assert result["total"] == 0
        assert result["wilderness_areas"] == []


class TestMalformedFeatures:
    def test_feature_without_attributes_key(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[{}], warnings=[]),
        )
        result = api.get_blm_land_use_plans_in_roi(38.5, -111.5)
        # A feature with no attributes should still parse to an "Unknown" plan.
        assert result["total"] == 1
        assert result["land_use_plans"][0]["plan_name"] == "Unknown"

    def test_null_attribute_values_do_not_crash(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(
                features=[{"attributes": {"NLCS_NAME": None, "Shape__Area": None, "DESIG_DATE": None}}],
                warnings=[],
            ),
        )
        result = api.get_blm_wilderness_areas_in_roi(38.5, -111.5)
        assert result["total"] == 1
        assert result["wilderness_areas"][0]["area_sq_mi"] is None
        assert result["wilderness_areas"][0]["designation_date"] is None

    def test_non_numeric_area_does_not_crash(self, monkeypatch):
        api = _load_blm_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(
                features=[{"attributes": {"NCA_NAME": "Some NM", "Shape__Area": "not-a-number"}}],
                warnings=[],
            ),
        )
        result = api.get_blm_national_monuments_in_roi(38.5, -111.5)
        assert result["total"] == 1
        assert result["national_monuments"][0]["area_sq_mi"] is None
