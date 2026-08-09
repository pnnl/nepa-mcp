"""
Unit tests for the EFH API layer (``efh/src/apis/efh_api.py``).

These exercise the pure parsing / dedup / area-clipping logic with the ArcGIS
query layer mocked, so no network calls are made. They follow the same dynamic
per-server import pattern used by ``test_five_server_updates.py`` and the area
mock pattern from ``test_point_buffer_area_rollout.py``.
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


def _load_efh_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "efh"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_efh_unit_api",
            server_dir / "src" / "apis" / "efh_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_efh_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _patch_query(api, monkeypatch, feature_map, warnings=None, truncated=False):
    """Return features keyed by service_name / url substring."""

    def query_features(url, _layer_id, _geometry, *, service_name=None, **_kwargs):
        for key, feats in feature_map.items():
            if key in (service_name or "") or key in url:
                return ArcGISFeatureQueryResult(features=feats, warnings=warnings or [], truncated=truncated)
        return ArcGISFeatureQueryResult(features=[], warnings=warnings or [])

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)


def _efh_feature(*, geometry=SIMPLE_GEOMETRY, acres=999.0, species="Pacific Coast Groundfish", zone="ALL"):
    feature = {
        "attributes": {
            "SITENAME_L": species,
            "LIFESTAGE": "ALL",
            "TYPE": "EFH",
            "FMC": "PFMC",
            "ZONE": zone,
            "ACRES": acres,
        }
    }
    if geometry is not None:
        feature["geometry"] = geometry
    return feature


# ---------------------------------------------------------------------------
# HAPC parsing
# ---------------------------------------------------------------------------


class TestHapc:
    def test_parses_hapc_fields(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "HAPC": [
                    {
                        "attributes": {
                            "HAPC_Siten": "Estuaries",
                            "FisheryM_5": "PFMC",
                            "LinkToRegu": "https://example.test/reg",
                            "DataCaveat": "caveat text",
                        }
                    }
                ]
            },
        )
        result = api.get_hapc_in_roi(46.5, -120.5, 25.0)
        assert result["total"] == 1
        h = result["hapc"][0]
        assert h["species"] == "Estuaries"
        assert h["fmc"] == "PFMC"
        assert h["type"] == "HAPC"
        assert h["title_link"] == "https://example.test/reg"
        assert result["center"] == {"latitude": 46.5, "longitude": -120.5}

    def test_deduplicates_by_species_and_fmc(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        feat = {"attributes": {"HAPC_Siten": "Estuaries", "FisheryM_5": "PFMC"}}
        _patch_query(api, monkeypatch, {"HAPC": [feat, dict(feat), dict(feat)]})
        result = api.get_hapc_in_roi(46.5, -120.5)
        assert result["total"] == 1

    def test_empty_features_yields_zero(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {})
        result = api.get_hapc_in_roi(46.5, -120.5)
        assert result["total"] == 0
        assert result["hapc"] == []


# ---------------------------------------------------------------------------
# General EFH areas (EFHA layer)
# ---------------------------------------------------------------------------


class TestEfhAreas:
    def test_parses_efha_fields(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "areas": [
                    {
                        "attributes": {
                            "SITENAME_L": "Coho salmon",
                            "TYPE": "EFHA",
                            "FMC_REPORT": "PFMC",
                            "LTTDT_LINK": "https://example.test/efha",
                        }
                    }
                ]
            },
        )
        result = api.get_efh_areas_in_roi(46.5, -120.5)
        assert result["total"] == 1
        area = result["efh_areas"][0]
        assert area["species"] == "Coho salmon"
        assert area["type"] == "EFHA"
        assert area["fmc"] == "PFMC"

    def test_deduplicates_efha(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        feat = {"attributes": {"SITENAME_L": "Coho salmon", "TYPE": "EFHA"}}
        _patch_query(api, monkeypatch, {"areas": [feat, dict(feat)]})
        result = api.get_efh_areas_in_roi(46.5, -120.5)
        assert result["total"] == 1


# ---------------------------------------------------------------------------
# Salmon EFH (HUC-8)
# ---------------------------------------------------------------------------


class TestSalmonEfh:
    def test_parses_watershed_fields(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "salmon": [
                    {
                        "attributes": {
                            "HUC_8": 17110006,
                            "HUC_8_Name": "Puget Sound",
                            "State": "WA",
                            "ChinookEFH": "Yes",
                            "Coho_EFH": "Yes",
                            "Pink_EFH": "No",
                            "All_EFH": "Yes",
                        }
                    }
                ]
            },
        )
        result = api.get_salmon_efh_in_roi(46.5, -120.5)
        assert result["total"] == 1
        w = result["watersheds"][0]
        assert w["huc_8"] == 17110006
        assert w["huc_8_name"] == "Puget Sound"
        assert w["chinook_efh"] == "Yes"

    def test_deduplicates_by_huc(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        feat = {"attributes": {"HUC_8": 17110006, "HUC_8_Name": "Puget Sound"}}
        _patch_query(api, monkeypatch, {"salmon": [feat, dict(feat), dict(feat)]})
        result = api.get_salmon_efh_in_roi(46.5, -120.5)
        assert result["total"] == 1


# ---------------------------------------------------------------------------
# HMS/CPS/Groundfish dedup + area clipping
# ---------------------------------------------------------------------------


class TestHmsAreaClipping:
    def test_duplicate_fragments_unioned_and_source_acres_retained(self, monkeypatch):
        api = _load_efh_api()
        feature = _efh_feature()
        one = api._deduplicate_efh([feature], roi_geometry=SIMPLE_GEOMETRY)[0]
        duplicate = api._deduplicate_efh([feature, feature], roi_geometry=SIMPLE_GEOMETRY)[0]
        # Clipped (geometry-derived) area comes back ok/complete.
        assert one["area_status"] == "ok"
        assert one["area_complete"] is True
        assert one["acres"] > 0
        # Union collapses duplicate geometry: clipped acreage is identical.
        assert duplicate["acres"] == one["acres"]
        # Source acreage is a straight sum of the ACRES attribute.
        assert duplicate["source_acres"] == 1_998.0
        assert one["source_acres"] == 999.0

    def test_missing_geometry_is_no_geometry_not_zero(self, monkeypatch):
        api = _load_efh_api()
        record = api._deduplicate_efh([_efh_feature(geometry=None)], roi_geometry=SIMPLE_GEOMETRY)[0]
        assert record["acres"] is None
        assert record["source_acres"] == 999.0
        assert record["area_status"] == "no_geometry"
        assert record["area_complete"] is False

    def test_no_roi_geometry_falls_back_to_source_attributes(self, monkeypatch):
        api = _load_efh_api()
        record = api._deduplicate_efh([_efh_feature()], roi_geometry=None)[0]
        assert record["area_status"] == "source_feature_attributes"
        assert record["acres"] == 999.0
        assert record["area_complete"] is None

    def test_truncated_geometry_marks_incomplete(self, monkeypatch):
        api = _load_efh_api()
        record = api._deduplicate_efh([_efh_feature()], roi_geometry=SIMPLE_GEOMETRY, geometry_complete=False)[0]
        assert record["area_complete"] is False
        assert any("understated" in w for w in record["area_warnings"])

    def test_hms_tool_end_to_end_clips_area(self, monkeypatch):
        api = _load_efh_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {"species": [_efh_feature()]})
        result = api.get_hms_cps_groundfish_efh_in_roi(46.5, -120.5)
        assert result["total"] == 1
        entry = result["efh_areas"][0]
        assert entry["area_status"] == "ok"
        assert entry["acres"] > 0
        assert entry["source_acres"] == 999.0


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


class TestFormatters:
    def test_hapc_summary_renders_markdown(self):
        api = _load_efh_api()
        data = {
            "center": {"latitude": 46.5, "longitude": -120.5},
            "buffer_miles": 25.0,
            "total": 1,
            "hapc": [{"species": "Estuaries", "fmc": "PFMC", "lifestage": "ALL", "zone": ""}],
            "warnings": [],
        }
        out = api.format_hapc_summary(data)
        assert "Habitat Areas of Particular Concern" in out
        assert "Estuaries" in out
        assert "HAPC designations found:** 1" in out

    def test_hapc_summary_handles_empty(self):
        api = _load_efh_api()
        data = {
            "center": {"latitude": 46.5, "longitude": -120.5},
            "buffer_miles": 25.0,
            "total": 0,
            "hapc": [],
            "warnings": [],
        }
        out = api.format_hapc_summary(data)
        assert "No Habitat Areas of Particular Concern found within the ROI." in out

    def test_salmon_summary_surfaces_marine_caveat_when_empty(self):
        api = _load_efh_api()
        data = {
            "center": {"latitude": 46.5, "longitude": -120.5},
            "buffer_miles": 25.0,
            "total": 0,
            "watersheds": [],
            "warnings": [],
        }
        out = api.format_salmon_efh_summary(data)
        assert "Marine salmon EFH caveat" in out

    def test_summary_surfaces_warnings(self):
        api = _load_efh_api()
        data = {
            "center": {"latitude": 46.5, "longitude": -120.5},
            "buffer_miles": 25.0,
            "total": 0,
            "efh_areas": [],
            "warnings": ["upstream degraded"],
        }
        out = api.format_efh_areas_summary(data)
        assert "Warning: upstream degraded" in out

    def test_area_provenance_labels_clipped_and_source(self):
        api = _load_efh_api()
        entry = {
            "species": "Pacific Coast Groundfish",
            "fmc": "PFMC",
            "lifestage": "ALL",
            "zone": "ALL",
            "acres": 12.5,
            "source_acres": 999.0,
            "area_status": "ok",
        }
        lines: list[str] = []
        api._append_efh_entries(lines, [entry])
        rendered = "\n".join(lines)
        assert "Area within ROI: 12.50 acres" in rendered
        assert "Source feature-area total (not clipped to ROI): 999.00 acres" in rendered

    def test_area_provenance_labels_no_geometry(self):
        api = _load_efh_api()
        entry = {
            "species": "Pacific Coast Groundfish",
            "fmc": "PFMC",
            "lifestage": "ALL",
            "zone": "ALL",
            "acres": None,
            "source_acres": 999.0,
            "area_status": "no_geometry",
        }
        lines: list[str] = []
        api._append_efh_entries(lines, [entry])
        rendered = "\n".join(lines)
        assert "Area within ROI: unavailable (no_geometry)" in rendered

    def test_area_provenance_labels_partial(self):
        api = _load_efh_api()
        entry = {
            "species": "Pacific Coast Groundfish",
            "fmc": "PFMC",
            "lifestage": "ALL",
            "zone": "ALL",
            "acres": 12.5,
            "source_acres": 999.0,
            "area_status": "ok",
            "area_complete": False,
        }
        lines: list[str] = []
        api._append_efh_entries(lines, [entry])
        assert "Partial area within ROI: 12.50 acres" in "\n".join(lines)
