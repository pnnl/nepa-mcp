"""
Unit tests for the tribal API layer (``tribal/src/apis/tribal_api.py``).

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
# AREALAND value (square meters) that converts to exactly 1.0 square mile.
ONE_SQ_MILE_METERS = 2589988.11


def _load_tribal_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "tribal"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_tribal_unit_api",
            server_dir / "src" / "apis" / "tribal_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_tribal_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: SIMPLE_GEOMETRY)


def _patch_query(api, monkeypatch, feature_map, warnings=None):
    """Return features keyed by service_name substring (layer name)."""

    def query_features(url, _layer_id, _geometry, *, service_name=None, **_kwargs):
        for key, feats in feature_map.items():
            if key in (service_name or "") or key in url:
                return ArcGISFeatureQueryResult(features=feats, warnings=warnings or [])
        return ArcGISFeatureQueryResult(features=[], warnings=warnings or [])

    monkeypatch.setattr(api.ArcGISService, "query_features", query_features)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


class TestTribalParsing:
    def test_parses_tribal_land_fields(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "Federal American Indian Reservations": [
                    {
                        "attributes": {
                            "NAME": "Navajo Nation Reservation",
                            "BASENAME": "Navajo Nation",
                            "GEOID": "2430",
                            "LSADC": "79",
                            "AREALAND": ONE_SQ_MILE_METERS,
                            "CENTLAT": "36.0",
                            "CENTLON": "-109.0",
                        }
                    }
                ]
            },
        )
        result = api.get_tribal_lands_in_roi(34.5, -106.5, 25.0)
        assert result["total"] == 1
        land = result["tribal_lands"][0]
        assert land["name"] == "Navajo Nation Reservation"
        assert land["basename"] == "Navajo Nation"
        assert land["geoid"] == "2430"
        assert land["type_code"] == "79"
        assert land["area_sq_mi"] == 1.0
        assert land["centroid_lat"] == "36.0"
        assert land["centroid_lon"] == "-109.0"
        assert land["category"] == "Federal American Indian Reservations"
        assert result["center"] == {"latitude": 34.5, "longitude": -106.5}
        assert result["buffer_miles"] == 25.0

    def test_area_conversion_rounds_to_two_places(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)
        # 5 sq mi worth of square meters -> 5.0 after conversion.
        _patch_query(
            api,
            monkeypatch,
            {"Hawaiian Home Lands": [{"attributes": {"NAME": "HHL", "AREALAND": ONE_SQ_MILE_METERS * 5}}]},
        )
        result = api.get_tribal_lands_in_roi(21.3, -157.8)
        assert result["tribal_lands"][0]["area_sq_mi"] == 5.0

    def test_missing_area_yields_none(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {"Tribal Subdivisions": [{"attributes": {"NAME": "Sub A"}}]},
        )
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        assert result["tribal_lands"][0]["area_sq_mi"] is None

    def test_unparseable_area_yields_none(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {"Tribal Subdivisions": [{"attributes": {"NAME": "Sub A", "AREALAND": "not-a-number"}}]},
        )
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        assert result["tribal_lands"][0]["area_sq_mi"] is None

    def test_missing_name_defaults_to_unknown(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {"Off-Reservation Trust Lands": [{"attributes": {}}]})
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        assert result["total"] == 1
        assert result["tribal_lands"][0]["name"] == "Unknown"

    def test_category_reflects_layer_name(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {"Alaska Native Regional Corporations": [{"attributes": {"NAME": "Ahtna"}}]},
        )
        result = api.get_tribal_lands_in_roi(61.0, -145.0)
        assert result["tribal_lands"][0]["category"] == "Alaska Native Regional Corporations"

    def test_results_sorted_by_name(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "Federal American Indian Reservations": [
                    {"attributes": {"NAME": "Zuni"}},
                    {"attributes": {"NAME": "acoma"}},
                    {"attributes": {"NAME": "Mescalero"}},
                ]
            },
        )
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        names = [land["name"] for land in result["tribal_lands"]]
        assert names == ["acoma", "Mescalero", "Zuni"]

    def test_features_from_multiple_layers_all_kept(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)
        _patch_query(
            api,
            monkeypatch,
            {
                "Federal American Indian Reservations": [{"attributes": {"NAME": "Fed Res"}}],
                "State American Indian Reservations": [{"attributes": {"NAME": "State Res"}}],
            },
        )
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        # No dedup across layers: both distinct records preserved.
        assert result["total"] == 2
        cats = {land["category"] for land in result["tribal_lands"]}
        assert cats == {"Federal American Indian Reservations", "State American Indian Reservations"}

    def test_empty_features_yields_zero(self, monkeypatch):
        api = _load_tribal_api()
        _patch_roi(api, monkeypatch)
        _patch_query(api, monkeypatch, {})
        result = api.get_tribal_lands_in_roi(34.5, -106.5)
        assert result["total"] == 0
        assert result["tribal_lands"] == []


# ---------------------------------------------------------------------------
# Formatter
# ---------------------------------------------------------------------------


class TestFormatter:
    def test_summary_renders_markdown(self, monkeypatch):
        api = _load_tribal_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "total": 1,
            "tribal_lands": [
                {
                    "name": "Navajo Nation Reservation",
                    "basename": "Navajo Nation",
                    "geoid": "2430",
                    "type_code": "79",
                    "area_sq_mi": 27413.32,
                    "centroid_lat": "36.0",
                    "centroid_lon": "-109.0",
                    "category": "Federal American Indian Reservations",
                }
            ],
            "warnings": [],
        }
        out = api.format_tribal_summary(data)
        assert "Tribal Lands within ROI" in out
        assert "Navajo Nation Reservation" in out
        assert "Federal American Indian Reservations (1):" in out
        assert "Total Tribal Areas: 1" in out
        assert "27413.32 sq mi" in out

    def test_summary_groups_by_category(self, monkeypatch):
        api = _load_tribal_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "total": 2,
            "tribal_lands": [
                {"name": "Fed Res", "area_sq_mi": None, "category": "Federal American Indian Reservations"},
                {"name": "State Res", "area_sq_mi": None, "category": "State American Indian Reservations"},
            ],
            "warnings": [],
        }
        out = api.format_tribal_summary(data)
        assert "Federal American Indian Reservations (1):" in out
        assert "State American Indian Reservations (1):" in out

    def test_summary_shows_area_na_when_missing(self, monkeypatch):
        api = _load_tribal_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "total": 1,
            "tribal_lands": [{"name": "No Area Land", "area_sq_mi": None, "category": "Tribal Subdivisions"}],
            "warnings": [],
        }
        out = api.format_tribal_summary(data)
        assert "Area N/A" in out

    def test_summary_surfaces_warnings(self, monkeypatch):
        api = _load_tribal_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "total": 0,
            "tribal_lands": [],
            "warnings": ["upstream degraded"],
        }
        out = api.format_tribal_summary(data)
        assert "Warning: upstream degraded" in out

    def test_summary_handles_empty_with_consultation_note(self, monkeypatch):
        api = _load_tribal_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "total": 0,
            "tribal_lands": [],
            "warnings": [],
        }
        out = api.format_tribal_summary(data)
        assert "No tribal land records were returned." in out
        assert "EO 13175" in out

    def test_summary_present_records_have_consultation_note(self, monkeypatch):
        api = _load_tribal_api()
        data = {
            "center": {"latitude": 34.5, "longitude": -106.5},
            "buffer_miles": 25.0,
            "total": 1,
            "tribal_lands": [
                {"name": "Fed Res", "area_sq_mi": None, "category": "Federal American Indian Reservations"}
            ],
            "warnings": [],
        }
        out = api.format_tribal_summary(data)
        assert "consultation planning" in out
