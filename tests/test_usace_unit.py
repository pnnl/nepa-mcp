"""
Unit tests for the USACE API layer (``usace/src/apis/usace_api.py``).

These exercise the pure parsing/formatting logic with the ArcGIS query layer
mocked, so no network calls are made. They follow the same dynamic per-server
import pattern used by ``test_five_server_updates.py``.
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


def _load_usace_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "usace"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_usace_unit_api",
            server_dir / "src" / "apis" / "usace_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_usace_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _patch_query(api, monkeypatch, feature_map, warnings=None):
    """Return features keyed by service_name substring."""

    def query_features(url, _layer_id, _geometry, *, service_name=None, **_kwargs):
        for key, feats in feature_map.items():
            if key in (service_name or "") or key in url:
                return ArcGISFeatureQueryResult(features=feats, warnings=warnings or [])
        return ArcGISFeatureQueryResult(features=[], warnings=warnings or [])

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)


# ---------------------------------------------------------------------------
# Regulatory districts
# ---------------------------------------------------------------------------


class TestRegulatoryDistricts:
    def test_parses_district_fields(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "Regulatory Boundary": [
                    {
                        "attributes": {
                            "ERO_FORMALNAME": "Albuquerque District",
                            "DIST_ABBR": "SPA",
                            "REPORTS_TO": "South Pacific Division",
                            "WEB_ADDR": "https://www.spa.usace.army.mil",
                        }
                    }
                ]
            },
        )
        result = api.get_usace_regulatory_district(34.5, -106.5, 25.0)
        assert result["total_districts"] == 1
        d = result["districts"][0]
        assert d["district_name"] == "Albuquerque District"
        assert d["district_abbreviation"] == "SPA"
        assert d["division_name"] == "South Pacific Division"
        assert d["website_url"].endswith("army.mil")
        assert result["center"] == {"latitude": 34.5, "longitude": -106.5}

    def test_deduplicates_by_district_name(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        one = {"attributes": {"ERO_FORMALNAME": "Albuquerque District", "DIST_ABBR": "SPA"}}
        _patch_query(api, monkeypatch, {"Regulatory Boundary": [one, dict(one), dict(one)]})
        result = api.get_usace_regulatory_district(34.5, -106.5)
        assert result["total_districts"] == 1

    def test_unknown_district_when_fields_missing(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {"Regulatory Boundary": [{"attributes": {}}]})
        result = api.get_usace_regulatory_district(34.5, -106.5)
        assert result["districts"][0]["district_name"] == "Unknown"

    def test_empty_features_yields_zero(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {})
        result = api.get_usace_regulatory_district(34.5, -106.5)
        assert result["total_districts"] == 0
        assert result["districts"] == []


# ---------------------------------------------------------------------------
# Wetland regions
# ---------------------------------------------------------------------------


class TestWetlandRegions:
    def test_maps_supplement_url(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {"Wetland Regions": [{"attributes": {"REGION": "Arid West", "MLRA_NAME": "MLRA 42"}}]},
        )
        result = api.get_wetland_regions_in_roi(34.5, -106.5)
        assert result["total_regions"] == 1
        region = result["regions"][0]
        assert region["region_name"] == "Arid West"
        assert region["supplement_url"].startswith("https://usace.contentdm.oclc.org")

    def test_unknown_region_has_blank_supplement(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {"Wetland Regions": [{"attributes": {"REGION": "Nowhere"}}]})
        result = api.get_wetland_regions_in_roi(34.5, -106.5)
        assert result["regions"][0]["supplement_url"] == ""

    def test_deduplicates_regions(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        feat = {"attributes": {"REGION": "Great Plains"}}
        _patch_query(api, monkeypatch, {"Wetland Regions": [feat, dict(feat)]})
        result = api.get_wetland_regions_in_roi(34.5, -106.5)
        assert result["total_regions"] == 1


# ---------------------------------------------------------------------------
# Wetland subregions
# ---------------------------------------------------------------------------


class TestWetlandSubregions:
    def test_maps_region_code_to_name(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {"Wetland Subregions": [{"attributes": {"ADS_SUB_NM": "Sub A", "ADS_REGSUP": "AW", "MLRARSYM": "42B"}}]},
        )
        result = api.get_wetland_subregions_in_roi(34.5, -106.5)
        sub = result["subregions"][0]
        assert sub["subregion_name"] == "Sub A"
        assert sub["parent_region"] == "Arid West"
        assert sub["subregion_code"] == "42B"

    def test_unmapped_code_falls_back_to_code(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {"Wetland Subregions": [{"attributes": {"ADS_SUB_NM": "Sub B", "ADS_REGSUP": "ZZ"}}]},
        )
        result = api.get_wetland_subregions_in_roi(34.5, -106.5)
        assert result["subregions"][0]["parent_region"] == "ZZ"

    def test_deduplicates_subregions(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        feat = {"attributes": {"ADS_SUB_NM": "Sub C", "ADS_REGSUP": "MW"}}
        _patch_query(api, monkeypatch, {"Wetland Subregions": [feat, dict(feat)]})
        result = api.get_wetland_subregions_in_roi(34.5, -106.5)
        assert result["total_subregions"] == 1


# ---------------------------------------------------------------------------
# Comprehensive analysis
# ---------------------------------------------------------------------------


class TestComprehensiveAnalysis:
    def test_combines_all_three_datasets(self, monkeypatch):
        api = _load_usace_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "Regulatory Boundary": [{"attributes": {"ERO_FORMALNAME": "Albuquerque District"}}],
                "Wetland Regions": [{"attributes": {"REGION": "Arid West"}}],
                "Wetland Subregions": [{"attributes": {"ADS_SUB_NM": "Sub A", "ADS_REGSUP": "AW"}}],
            },
        )
        result = api.analyze_usace_jurisdiction(34.5, -106.5)
        assert result["regulatory_districts"]["total_districts"] == 1
        assert result["wetland_regions"]["total_regions"] == 1
        assert result["wetland_subregions"]["total_subregions"] == 1


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


class TestFormatters:
    def test_districts_summary_renders_markdown(self, monkeypatch):
        api = _load_usace_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "total_districts": 1,
            "districts": [
                {
                    "district_name": "Albuquerque District",
                    "district_abbreviation": "SPA",
                    "division_name": "South Pacific Division",
                    "division_abbreviation": "SPD",
                    "website_url": "https://www.spa.usace.army.mil",
                    "phone": "",
                    "address": "",
                }
            ],
            "warnings": [],
        }
        out = api.format_usace_districts_summary(data)
        assert "USACE Regulatory Districts" in out
        assert "Albuquerque District" in out
        assert "Districts Found: 1" in out

    def test_districts_summary_handles_empty(self, monkeypatch):
        api = _load_usace_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "total_districts": 0,
            "districts": [],
            "warnings": [],
        }
        out = api.format_usace_districts_summary(data)
        assert "No USACE districts found in ROI." in out

    def test_summary_surfaces_warnings(self, monkeypatch):
        api = _load_usace_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "total_regions": 0,
            "regions": [],
            "warnings": ["upstream degraded"],
        }
        out = api.format_wetland_regions_summary(data)
        assert "Warning: upstream degraded" in out

    def test_comprehensive_summary_has_section_404_notes(self, monkeypatch):
        api = _load_usace_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "regulatory_districts": {"districts": [], "warnings": []},
            "wetland_regions": {"regions": [], "warnings": []},
            "wetland_subregions": {"subregions": [], "warnings": []},
        }
        out = api.format_comprehensive_analysis_summary(data)
        assert "Section 404 Compliance Notes:" in out
        assert "Nationwide permits may be available" in out
