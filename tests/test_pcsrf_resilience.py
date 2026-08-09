"""
Resilience tests for the PCSRF API layer.

Verify graceful behavior when the upstream ArcGIS service errors, times out,
returns malformed payloads, or truncates results. The PCSRF ``_query_layer``
helper catches exceptions and degrades to an empty-plus-warning result rather
than propagating, so most failures surface as warnings, not raised errors.
The shared ArcGISService is mocked to simulate each failure mode.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-121.0, 46.0], [-120.0, 46.0], [-120.0, 47.0], [-121.0, 47.0], [-121.0, 46.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_pcsrf_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "pcsrf"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_pcsrf_resilience_api", server_dir / "src" / "apis" / "pcsrf_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_pcsrf_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _ch_poly_feature(*, geometry=SIMPLE_GEOMETRY, area=999.0):
    feature = {
        "attributes": {
            "COMNAME": "Test salmon",
            "LISTENTITY": "Test salmon DPS",
            "LISTSTATUS": "Threatened",
            "UNIT": "Unit A",
            "AREASqKm": area,
        }
    }
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


class TestUpstreamQueryFailure:
    def test_query_error_degrades_to_warning_not_raise(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)

        def boom(*_a, **_k):
            raise RuntimeError("PCSRF species ranges upstream 500")

        monkeypatch.setattr(api.ArcGISService, "query_features", boom)
        # _query_layer swallows the exception; the tool returns empty + warning.
        result = api.get_species_ranges_in_roi(46.5, -120.5)
        assert result["total"] == 0
        assert any("query failed" in w for w in result["warnings"])

    def test_timeout_degrades_to_warning(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)

        import requests as req_mod

        def timeout(*_a, **_k):
            raise req_mod.exceptions.Timeout("timed out")

        monkeypatch.setattr(api.ArcGISService, "query_features", timeout)
        result = api.get_pcsrf_projects_in_roi(46.5, -120.5)
        assert result["total"] == 0
        assert any("query failed" in w for w in result["warnings"])

    def test_buffer_creation_failure_returns_empty_error(self, monkeypatch):
        api = _load_pcsrf_api()
        monkeypatch.setattr(
            api.ArcGISService,
            "create_roi_buffer",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("buffer boom")),
        )
        result = api.get_critical_habitat_in_roi(46.5, -120.5)
        assert result["total"] == 0
        assert result.get("error") == "Buffer creation failed"


class TestDegradedButUsable:
    def test_truncation_marks_polygon_area_incomplete(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)

        def query_features(url, _layer_id, _geometry, *, service_name=None, **_k):
            if "polygon" in (service_name or "").lower():
                return ArcGISFeatureQueryResult(
                    features=[_ch_poly_feature()],
                    warnings=["reached the feature safety cap; results are partial."],
                    truncated=True,
                )
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_critical_habitat_in_roi(46.5, -120.5)
        assert result["total"] == 1
        assert result["habitats"][0]["area_complete"] is False
        assert any("safety cap" in w for w in result["warnings"])
        assert any("may be understated" in w for w in result["warnings"])

    def test_empty_features_is_not_an_error(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[], warnings=[]),
        )
        result = api.get_efh_in_roi(44.8, -68.8)
        assert result["total"] == 0
        assert result["efh_areas"] == []
        assert "error" not in result


class TestMalformedFeatures:
    def test_feature_without_attributes_key(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[{}], warnings=[]),
        )
        # A feature with no attributes should still parse without crashing.
        result = api.get_species_ranges_in_roi(46.5, -120.5)
        assert result["total"] == 1

    def test_null_attribute_values_do_not_crash(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(
                features=[{"attributes": {"PROJECT_NAME": None, "PCSRF_FUNDS": None, "STATUS": None}}], warnings=[]
            ),
        )
        result = api.get_pcsrf_projects_in_roi(46.5, -120.5)
        assert result["total"] == 1
        assert result["total_pcsrf_funding"] == 0

    def test_missing_polygon_geometry_marks_no_geometry(self, monkeypatch):
        api = _load_pcsrf_api()
        _patch_roi(api, monkeypatch)

        def query_features(url, _layer_id, _geometry, *, service_name=None, **_k):
            if "polygon" in (service_name or "").lower():
                return ArcGISFeatureQueryResult(features=[_ch_poly_feature(geometry=None)], warnings=[])
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_critical_habitat_in_roi(46.5, -120.5)
        assert result["habitats"][0]["area_status"] == "no_geometry"
        assert result["habitats"][0]["area_sqkm"] is None
        assert result["habitats"][0]["source_area_sqkm"] == 999.0

    def test_line_geometry_fed_to_polygon_path_is_skipped(self):
        api = _load_pcsrf_api()
        valid = _ch_poly_feature()
        invalid = {
            "attributes": {"LISTENTITY": "Test salmon DPS", "UNIT": "Unit A", "AREASqKm": 2.0},
            "geometry": {"paths": [[[0.0, 0.0], [1.0, 1.0]]]},
        }
        record = api._deduplicate_ch_fragments([valid, invalid], "polygon", roi_geometry=SIMPLE_GEOMETRY)[0]
        assert record["area_status"] == "ok"
        assert record["area_complete"] is False
        assert any("Line paths" in w for w in record["area_warnings"])
