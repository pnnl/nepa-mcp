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
        assert rec["gis_acres"] == 0.0

    def test_gis_acres_rounded_to_two_places(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, [{"attributes": {"GIS_Acres": 123.45678}}])
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["records"][0]["gis_acres"] == 123.46

    def test_non_numeric_gis_acres_coerced_to_zero(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, [{"attributes": {"GIS_Acres": "not-a-number"}}])
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["records"][0]["gis_acres"] == 0.0

    def test_empty_features_yields_zero(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, [])
        result = api.get_padus_in_roi(34.5, -106.5)
        assert result["total_records"] == 0
        assert result["records"] == []

    def test_requests_combined_layer_category_without_geometry(self, monkeypatch):
        api = _load_padus_api()
        _patch_roi(api, monkeypatch)
        captured = {}

        def query_features(*args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return ArcGISFeatureQueryResult(features=[], warnings=[])

        monkeypatch.setattr(api.ArcGISService, "query_features", query_features)
        api.get_padus_in_roi(34.5, -106.5)

        assert captured["args"][:2] == (api.PADUS_BASE_URL, api.PADUS_COMBINED_LAYER)
        assert "Category" in captured["kwargs"]["out_fields"].split(",")
        assert captured["kwargs"].get("return_geometry", False) is False
        assert "out_sr" not in captured["kwargs"]


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
    def _data(self, records, warnings=None):
        return {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "total_records": len(records),
            "records": records,
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
        )
        out = api.format_padus_summary(data)
        assert "Total PAD-US Records: 2" in out
        assert "PAD-US Protected-Area Records by Owner Type:" in out
        assert "Federal (FED): 2 records" in out
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

    def test_summary_warns_that_source_feature_acres_are_not_roi_area(self, monkeypatch):
        api = _load_padus_api()
        out = api.format_padus_summary(self._data([]))
        assert "full mapped area of each intersecting source feature" in out
        assert "source-feature acreages are not additive" in out
        assert "do not represent total land area within the ROI" in out

    def test_summary_surfaces_warnings(self, monkeypatch):
        api = _load_padus_api()
        out = api.format_padus_summary(self._data([], warnings=["upstream degraded"]))
        assert "Warning: upstream degraded" in out

    def test_top_records_fall_back_to_owner_name_when_no_unit(self, monkeypatch):
        api = _load_padus_api()
        data = self._data(
            [{"category": "Fee", "owner_type": "FED", "owner_name": "BLM", "unit_name": "", "gis_acres": 42.0}]
        )
        out = api.format_padus_summary(data)
        assert "BLM (Fee; FED)" in out
