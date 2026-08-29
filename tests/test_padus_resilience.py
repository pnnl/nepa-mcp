"""
Resilience tests for the PADUS API layer.

Verify graceful behavior when the upstream ArcGIS service errors, times out,
returns malformed payloads, or truncates results. The shared ArcGISService is
mocked to simulate each failure mode.
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


def _load_padus_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "padus"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_padus_resilience_api", server_dir / "src" / "apis" / "padus_api.py"
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_padus_resilience_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


class TestUpstreamQueryFailure:
    def test_buffer_failure_returns_explicitly_unavailable_result(self, monkeypatch):
        api = _load_padus_api()
        monkeypatch.setattr(
            api.ArcGISService,
            "create_roi_buffer",
            lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("geometry service unavailable")),
        )
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["query_status"] == "unavailable"
        assert result["total_records"] is None

    def test_malformed_buffer_value_error_returns_unavailable_result(self, monkeypatch):
        api = _load_padus_api()

        def malformed_buffer(*_a, **_k):
            raise ValueError("no buffered geometries")

        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", malformed_buffer)
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["query_status"] == "unavailable"
        assert any("no buffered geometries" in warning for warning in result["warnings"])

    def test_query_failure_returns_explicitly_unavailable_result(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)

        def boom(*_a, **_k):
            raise RuntimeError("PAD-US Fee layer upstream 500")

        monkeypatch.setattr(api.ArcGISService, "query_features", boom)
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["query_status"] == "unavailable"
        assert result["total_records"] is None
        assert result["roi_area_status"] == "unavailable"

    def test_timeout_returns_explicitly_unavailable_result(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)

        import requests as req_mod

        def timeout(*_a, **_k):
            raise req_mod.exceptions.Timeout("timed out")

        monkeypatch.setattr(api.ArcGISService, "query_features", timeout)
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["query_status"] == "unavailable"
        assert result["total_records"] is None

    def test_geometry_failure_falls_back_to_records_without_area(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        calls = []

        def query_features(*_a, **kwargs):
            calls.append(kwargs)
            if kwargs["return_geometry"]:
                raise RuntimeError("geometry query timed out")
            return ArcGISFeatureQueryResult(
                features=[{"attributes": {"Category": "Fee", "Own_Type": "FED", "Own_Name": "BLM"}}],
                warnings=[],
            )

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_padus_in_roi(34.5, -106.5)
        assert [call["return_geometry"] for call in calls] == [True, False]
        assert result["query_status"] == "degraded"
        assert result["total_records"] == 1
        assert result["area_by_owner_type"]["FED"]["acres_within_roi"] is None


class TestDegradedButUsable:
    def test_warnings_are_carried_through(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)

        def query_features(*_a, **_k):
            return ArcGISFeatureQueryResult(
                features=[
                    {
                        "attributes": {"Category": "Fee", "Own_Type": "FED", "Own_Name": "BLM"},
                        "geometry": SIMPLE_GEOMETRY,
                    }
                ],
                warnings=["reached the feature safety cap; results are partial."],
                truncated=True,
            )

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["total_records"] == 1
        assert any("safety cap" in w for w in result["warnings"])
        area = result["area_by_owner_type"]["FED"]
        assert area["area_complete"] is False
        assert area["acres_within_roi"] is None
        assert area["area_status"] == "incomplete_query"

    def test_empty_features_is_not_an_error(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[], warnings=[]),
        )
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["total_records"] == 0
        assert result["records"] == []

    def test_geometry_over_complexity_limit_withholds_area(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(api, "PADUS_MAX_TOTAL_VERTICES", 4)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(
                features=[{"attributes": {"Own_Type": "FED"}, "geometry": SIMPLE_GEOMETRY}],
                warnings=[],
            ),
        )
        area = api.get_padus_in_roi(34.5, -106.5)["area_by_owner_type"]["FED"]
        assert area["acres_within_roi"] is None
        assert area["area_status"] == "complexity_limit"


class TestMalformedFeatures:
    def test_non_mapping_feature_is_skipped_and_marks_records_incomplete(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=["bad feature"], warnings=[]),
        )
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["total_records"] == 1
        assert result["parsed_records"] == 0
        assert result["records_complete"] is False
        assert result["roi_area_status"] == "unavailable"
        assert result["query_status"] == "degraded"

    def test_feature_without_attributes_key(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=[{}], warnings=[]),
        )
        result = api.get_padus_in_roi(34.5, -106.5)
        # A feature with no attributes should still parse to an "Unknown" owner record.
        assert result["total_records"] == 1
        assert result["records"][0]["owner_type"] == "Unknown"

    def test_null_attribute_values_do_not_crash(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(
                features=[{"attributes": {"Own_Type": None, "GIS_Acres": None}}], warnings=[]
            ),
        )
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["total_records"] == 1
        assert result["records"][0]["gis_acres"] is None
        assert result["records"][0]["source_gis_acres_available"] is False

    def test_malformed_sort_fields_and_non_finite_acres_are_normalized(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(
                features=[
                    {
                        "attributes": {
                            "Category": None,
                            "Own_Type": 7,
                            "Own_Name": ["owner"],
                            "Unit_Nm": None,
                            "GIS_Acres": "nan",
                        }
                    }
                ],
                warnings=[],
            ),
        )
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["records"][0]["category"] == "Unknown"
        assert result["records"][0]["owner_type"] == "7"
        assert result["records"][0]["gis_acres"] is None

    def test_null_features_payload_is_not_misreported_as_zero_records(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        monkeypatch.setattr(
            api.ArcGISService,
            "query_features",
            lambda *_a, **_k: ArcGISFeatureQueryResult(features=None, warnings=[]),
        )
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["total_records"] is None
        assert result["records"] == []
        assert result["records_complete"] is False
        assert result["query_status"] == "unavailable"

    def test_non_finite_geometry_is_withheld_without_crashing(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        for invalid_coordinate in (float("nan"), float("inf")):
            geometry = {
                "rings": [
                    [
                        [invalid_coordinate, 34.0],
                        [-106.0, 34.0],
                        [-106.0, 35.0],
                        [invalid_coordinate, 34.0],
                    ]
                ],
                "spatialReference": {"wkid": 4326},
            }
            monkeypatch.setattr(
                api.ArcGISService,
                "query_features",
                lambda *_a, _geometry=geometry, **_k: ArcGISFeatureQueryResult(
                    features=[{"attributes": {"Own_Type": "FED"}, "geometry": _geometry}],
                    warnings=[],
                ),
            )
            area = api.get_padus_in_roi(34.5, -106.5)["area_by_owner_type"]["FED"]
            assert area["acres_within_roi"] is None
            assert area["area_complete"] is False
