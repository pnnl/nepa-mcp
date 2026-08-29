"""
Unit tests for the PADUS API layer (``padus/src/apis/padus_api.py``).

These exercise the pure parsing/formatting logic with the ArcGIS query layer
mocked, so no network calls are made. They follow the same dynamic per-server
import pattern used by ``test_usace_unit.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from nepa_mcp_common.arcgis import ArcGISFeatureQueryResult
from nepa_mcp_common.spatial import AreaUnit, clipped_union_area_from_esri_geometries

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}
FEATURE_GEOMETRY = {
    "rings": [[[-106.9, 34.1], [-106.4, 34.1], [-106.4, 34.6], [-106.9, 34.6], [-106.9, 34.1]]],
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
            "_padus_unit_api",
            server_dir / "src" / "apis" / "padus_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_padus_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _patch_query(api, monkeypatch, features, warnings=None):
    monkeypatch.setattr(
        api.ArcGISService,
        "query_features",
        lambda *_a, **_k: ArcGISFeatureQueryResult(features=features, warnings=warnings or []),
    )


# ---------------------------------------------------------------------------
# Record parsing
# ---------------------------------------------------------------------------


class TestRecordParsing:
    def test_parses_all_record_fields(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            [
                {
                    "attributes": {
                        "Category": "Designation",
                        "Own_Type": "FED",
                        "Own_Name": "BLM",
                        "Mang_Type": "FED",
                        "Mang_Name": "BLM",
                        "Des_Tp": "National Monument",
                        "Unit_Nm": "Rio Grande del Norte",
                        "State_Nm": "NM",
                        "GIS_Acres": 242455.5,
                        "GAP_Sts": "2",
                        "IUCN_Cat": "III",
                        "Date_Est": "2013",
                    }
                }
            ],
        )
        result = api.get_padus_in_roi(34.5, -106.5, 25.0)
        assert result["total_records"] == 1
        rec = result["records"][0]
        assert rec["category"] == "Designation"
        assert rec["owner_type"] == "FED"
        assert rec["owner_name"] == "BLM"
        assert rec["manager_type"] == "FED"
        assert rec["manager_name"] == "BLM"
        assert rec["designation_type"] == "National Monument"
        assert rec["unit_name"] == "Rio Grande del Norte"
        assert rec["state"] == "NM"
        assert rec["gis_acres"] == 242455.5
        assert rec["source_gis_acres"] == 242455.5
        assert rec["source_gis_acres_available"] is True
        assert rec["gap_status"] == "2"
        assert rec["iucn_category"] == "III"
        assert rec["date_established"] == "2013"
        assert result["center"] == {"latitude": 34.5, "longitude": -106.5}
        assert result["buffer_miles"] == 25.0

    def test_missing_fields_fall_back_to_defaults(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, [{"attributes": {}}])
        result = api.get_padus_in_roi(34.5, -106.5)
        rec = result["records"][0]
        assert rec["category"] == "Unknown"
        assert rec["owner_type"] == "Unknown"
        assert rec["owner_name"] == "Unknown"
        assert rec["manager_type"] == ""
        assert rec["gis_acres"] is None
        assert rec["source_gis_acres"] is None
        assert rec["source_gis_acres_available"] is False
        owner_area = result["area_by_owner_type"]["Unknown"]
        assert owner_area["source_feature_acres"] is None
        assert owner_area["source_feature_acres_complete"] is False
        assert owner_area["source_feature_acres_missing_records"] == 1

    def test_gis_acres_rounded_to_two_places(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, [{"attributes": {"GIS_Acres": 123.45678}}])
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["records"][0]["gis_acres"] == 123.46

    def test_zero_gis_acres_is_available_not_missing(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, [{"attributes": {"Own_Type": "FED", "GIS_Acres": 0}}])
        result = api.get_padus_in_roi(34.5, -106.5)
        record = result["records"][0]
        assert record["gis_acres"] == 0.0
        assert record["source_gis_acres_available"] is True
        assert result["area_by_owner_type"]["FED"]["source_feature_acres"] == 0.0

    def test_non_numeric_gis_acres_is_marked_unavailable(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, [{"attributes": {"GIS_Acres": "not-a-number"}}])
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["records"][0]["gis_acres"] is None
        assert result["records"][0]["source_gis_acres_available"] is False

    def test_missing_source_acres_does_not_invalidate_complete_roi_geometry(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            [
                {
                    "attributes": {"Category": "Fee", "Own_Type": "FED", "GIS_Acres": None},
                    "geometry": FEATURE_GEOMETRY,
                }
            ],
        )
        result = api.get_padus_in_roi(34.5, -106.5)
        area = result["area_by_owner_type"]["FED"]
        assert result["roi_area_status"] == "complete"
        assert area["acres_within_roi"] is not None
        assert area["source_feature_acres"] is None
        assert area["source_feature_acres_complete"] is False
        assert area["source_feature_acres_missing_records"] == 1

    def test_empty_features_yields_zero(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, [])
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["total_records"] == 0
        assert result["records"] == []

    def test_requests_combined_layer_category_and_wgs84_geometry(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        captured = {}

        def query_features(*args, **kwargs):
            captured["args"] = args
            captured.update(kwargs)
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        api.get_padus_in_roi(34.5, -106.5)

        assert captured["args"][:2] == (api.PADUS_BASE_URL, api.PADUS_COMBINED_LAYER)
        assert "Category" in captured["out_fields"].split(",")
        assert captured["return_geometry"] is True
        assert captured["out_sr"] == 4326
        assert captured["max_attempts"] == 1
        assert captured["max_features"] == api.PADUS_MAX_FEATURES
        assert captured["page_size"] == api.PADUS_MAX_FEATURES
        assert captured["timeout"] == api.PADUS_QUERY_TIMEOUT
        assert captured["strict_features"] is True
        assert captured["extra_params"] == {
            "maxAllowableOffset": api.PADUS_MAX_ALLOWABLE_OFFSET_DEGREES,
            "geometryPrecision": 5,
        }

    def test_duplicate_geometries_are_unioned_before_clipping(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        feature = {
            "attributes": {"Category": "Designation", "Own_Type": "DESG", "GIS_Acres": 999},
            "geometry": FEATURE_GEOMETRY,
        }
        _patch_query(api, monkeypatch, [feature, feature])

        result = api.get_padus_in_roi(34.5, -106.5)
        area = result["area_by_owner_type"]["DESG"]
        expected = clipped_union_area_from_esri_geometries([FEATURE_GEOMETRY], SIMPLE_GEOMETRY).area(AreaUnit.ACRES)
        assert area["acres_within_roi"] == pytest.approx(expected, abs=0.01)
        assert area["source_feature_acres"] == 1998.0
        assert area["area_complete"] is True

    def test_incomplete_owner_geometry_does_not_publish_partial_acres(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            [
                {"attributes": {"Own_Type": "FED"}, "geometry": FEATURE_GEOMETRY},
                {"attributes": {"Own_Type": "FED"}, "geometry": None},
            ],
        )
        result = api.get_padus_in_roi(34.5, -106.5)
        area = result["area_by_owner_type"]["FED"]
        assert area["area_complete"] is False
        assert area["acres_within_roi"] is None

    def test_collapsed_ring_does_not_discard_valid_multipart_geometry(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        collapsed_ring = [[-106.5, 34.2], [-106.5, 34.3], [-106.5, 34.2], [-106.5, 34.2]]
        multipart_geometry = {
            "rings": [*FEATURE_GEOMETRY["rings"], collapsed_ring],
            "spatialReference": {"wkid": 4326},
        }
        _patch_query(
            api,
            monkeypatch,
            [{"attributes": {"Own_Type": "FED"}, "geometry": multipart_geometry}],
        )
        area = api.get_padus_in_roi(34.5, -106.5)["area_by_owner_type"]["FED"]
        assert area["area_complete"] is True
        assert area["acres_within_roi"] is not None
        assert any("collapsed or non-polygon ring" in warning for warning in area["area_warnings"])


# ---------------------------------------------------------------------------
# Sorting
# ---------------------------------------------------------------------------


class TestSorting:
    def test_records_sorted_by_owner_then_unit(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            [
                {"attributes": {"Own_Type": "STAT", "Own_Name": "NM State", "Unit_Nm": "Z Park"}},
                {"attributes": {"Own_Type": "FED", "Own_Name": "BLM", "Unit_Nm": "B Unit"}},
                {"attributes": {"Own_Type": "FED", "Own_Name": "BLM", "Unit_Nm": "A Unit"}},
            ],
        )
        result = api.get_padus_in_roi(34.5, -106.5)
        order = [(r["owner_type"], r["unit_name"]) for r in result["records"]]
        assert order == [("FED", "A Unit"), ("FED", "B Unit"), ("STAT", "Z Park")]


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class TestFormatter:
    def _data(self, records, warnings=None, area_by_owner_type=None):
        return {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "total_records": len(records),
            "records": records,
            "area_by_owner_type": area_by_owner_type or {},
            "warnings": warnings or [],
        }

    def test_summary_renders_header_and_owner_group(self, monkeypatch):
        api = _load_padus_api()
        data = self._data(
            [
                {
                    "category": "Fee",
                    "owner_type": "FED",
                    "owner_name": "BLM",
                    "unit_name": "Rio Grande del Norte",
                    "gis_acres": 1000.0,
                },
                {
                    "category": "Fee",
                    "owner_type": "FED",
                    "owner_name": "USFS",
                    "unit_name": "Carson NF",
                    "gis_acres": 500.0,
                },
            ],
            area_by_owner_type={
                "FED": {
                    "acres_within_roi": 1250.0,
                    "area_complete": True,
                    "area_warnings": [],
                }
            },
        )
        out = api.format_padus_summary(data)
        assert "Total PAD-US Records: 2" in out
        assert "PAD-US Protected-Area Records by Owner Type:" in out
        assert "Federal (FED): 2 records, approximately 1,250 acres within ROI" in out
        assert "PAD-US Records by Category:" in out
        assert "Fee: 2 records" in out
        assert "Top 10 Largest Intersecting Source Features by Full Mapped Acreage (not clipped to ROI):" in out
        assert "Rio Grande del Norte (Fee; FED)" in out
        assert "1,000 source-feature acres" in out
        assert "USGS Protected Areas Database (PAD-US) v4.1" in out

    def test_summary_handles_empty(self, monkeypatch):
        api = _load_padus_api()
        out = api.format_padus_summary(self._data([]))
        assert "Total PAD-US Records: 0" in out
        # No records => no "Top 10" section.
        assert "Top 10 Largest Records" not in out

    def test_summary_explains_source_and_roi_acreage(self, monkeypatch):
        api = _load_padus_api()
        out = api.format_padus_summary(self._data([]))
        assert "full mapped area of each intersecting source feature" in out
        assert "ROI acreage is clipped and unioned within each owner type" in out
        assert "geometry is simplified to about 11 meters" in out

    def test_summary_surfaces_warnings(self, monkeypatch):
        api = _load_padus_api()
        out = api.format_padus_summary(self._data([], warnings=["upstream degraded"]))
        assert "Warning: upstream degraded" in out

    def test_summary_distinguishes_unavailable_from_zero_records(self, monkeypatch):
        api = _load_padus_api()
        data = self._data([], warnings=["upstream unavailable"])
        data.update({"total_records": None, "records_complete": False})
        out = api.format_padus_summary(data)
        assert "Total PAD-US Records: unavailable" in out
        assert "Total PAD-US Records: 0" not in out

    def test_summary_marks_truncated_record_count_partial(self, monkeypatch):
        api = _load_padus_api()
        data = self._data([])
        data.update({"total_records": 2000, "records_complete": False})
        out = api.format_padus_summary(data)
        assert "Total PAD-US Records: at least 2,000 (partial response)" in out

    def test_summary_labels_missing_source_acreage_unavailable(self, monkeypatch):
        api = _load_padus_api()
        data = self._data(
            [
                {
                    "category": "Fee",
                    "owner_type": "FED",
                    "owner_name": "BLM",
                    "unit_name": "Unknown Unit",
                    "gis_acres": None,
                }
            ]
        )
        out = api.format_padus_summary(data)
        assert "Unknown Unit (Fee; FED) - source-feature acreage unavailable" in out

    def test_top_records_fall_back_to_owner_name_when_no_unit(self, monkeypatch):
        api = _load_padus_api()
        data = self._data(
            [{"category": "Fee", "owner_type": "FED", "owner_name": "BLM", "unit_name": "", "gis_acres": 42.0}]
        )
        out = api.format_padus_summary(data)
        assert "BLM (Fee; FED)" in out
