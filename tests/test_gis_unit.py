"""
Unit tests for the GIS/ROI API layer (``gis/src/apis/roi_api.py``).

These exercise the pure geometry/area/formatting logic with the ArcGIS buffer
call mocked, so no network calls are made. They follow the same dynamic
per-server import pattern used by ``test_usace_unit.py``.

Note: on this branch the GIS API is fully stateless -- ``calculate_roi_area``
is pure math over the buffer geometry, and ``get_roi_geojson`` builds a GeoJSON
FeatureCollection. Neither writes files. The only network dependency is
``ArcGISService.create_roi_buffer``, which we mock.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIMPLE_GEOMETRY = {
    "rings": [[[-107.0, 34.0], [-106.0, 34.0], [-106.0, 35.0], [-107.0, 35.0], [-107.0, 34.0]]],
    "spatialReference": {"wkid": 4326},
}


def _load_roi_api():
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            sys.modules.pop(module_name, None)
    server_dir = ROOT / "gis"
    sys.path.insert(0, str(server_dir))
    try:
        spec = importlib.util.spec_from_file_location(
            "_gis_unit_api",
            server_dir / "src" / "apis" / "roi_api.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        sys.modules["_gis_unit_api"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(server_dir))


def _patch_roi(api, monkeypatch, geometry=SIMPLE_GEOMETRY):
    monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", lambda *_a, **_k: geometry)


# ---------------------------------------------------------------------------
# calculate_roi_area (pure math over buffer geometry)
# ---------------------------------------------------------------------------


class TestCalculateRoiArea:
    def test_returns_square_miles_and_acres(self, monkeypatch):
        api = _load_roi_api()
        _patch_roi(api, monkeypatch)
        sq_miles, acres = api.calculate_roi_area(34.5, -106.5, 25.0)
        # Values are deterministic for the fixed SIMPLE_GEOMETRY.
        assert sq_miles == 5865.26
        assert acres == 3753768.0

    def test_area_is_rounded(self, monkeypatch):
        api = _load_roi_api()
        _patch_roi(api, monkeypatch)
        sq_miles, acres = api.calculate_roi_area(34.5, -106.5)
        # square_miles rounded to 2 dp, acres to whole number.
        assert round(sq_miles, 2) == sq_miles
        assert acres == round(acres)

    def test_passes_arguments_to_buffer(self, monkeypatch):
        api = _load_roi_api()
        captured = {}

        def fake_buffer(lat, lon, buffer_miles):
            captured["args"] = (lat, lon, buffer_miles)
            return SIMPLE_GEOMETRY

        monkeypatch.setattr(api.ArcGISService, "create_roi_buffer", fake_buffer)
        api.calculate_roi_area(40.7128, -74.0060, 10.0)
        assert captured["args"] == (40.7128, -74.0060, 10.0)


# ---------------------------------------------------------------------------
# get_roi_geojson (FeatureCollection assembly)
# ---------------------------------------------------------------------------


class TestGetRoiGeojson:
    def test_feature_collection_shape(self, monkeypatch):
        api = _load_roi_api()
        _patch_roi(api, monkeypatch)
        gj = api.get_roi_geojson(34.5, -106.5, 25.0)
        assert gj["type"] == "FeatureCollection"
        assert len(gj["features"]) == 2

    def test_point_feature_holds_center(self, monkeypatch):
        api = _load_roi_api()
        _patch_roi(api, monkeypatch)
        gj = api.get_roi_geojson(34.5, -106.5, 25.0)
        point = gj["features"][0]
        assert point["geometry"]["type"] == "Point"
        # GeoJSON order is [lon, lat].
        assert point["geometry"]["coordinates"] == [-106.5, 34.5]
        assert point["properties"]["type"] == "Project Location"

    def test_polygon_feature_carries_buffer_geometry(self, monkeypatch):
        api = _load_roi_api()
        _patch_roi(api, monkeypatch)
        gj = api.get_roi_geojson(34.5, -106.5, 25.0)
        polygon = gj["features"][1]
        assert polygon["geometry"]["type"] == "Polygon"
        assert polygon["geometry"]["coordinates"] == SIMPLE_GEOMETRY["rings"]
        assert polygon["properties"]["type"] == "Region of Interest"
        assert polygon["properties"]["buffer_miles"] == 25.0

    def test_metadata_center_buffer_and_area(self, monkeypatch):
        api = _load_roi_api()
        _patch_roi(api, monkeypatch)
        gj = api.get_roi_geojson(34.5, -106.5, 25.0)
        meta = gj["metadata"]
        assert meta["center"] == {"latitude": 34.5, "longitude": -106.5}
        assert meta["buffer_miles"] == 25.0
        assert meta["area"]["square_miles"] == 5865.26
        assert meta["area"]["acres"] == 3753768.0

    def test_metadata_extent_matches_geometry(self, monkeypatch):
        api = _load_roi_api()
        _patch_roi(api, monkeypatch)
        gj = api.get_roi_geojson(34.5, -106.5, 25.0)
        extent = gj["metadata"]["extent"]
        assert extent == {"north": 35.0, "south": 34.0, "east": -106.0, "west": -107.0}


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------


class TestFormatters:
    def test_area_summary_renders(self, monkeypatch):
        api = _load_roi_api()
        out = api.format_area_summary(34.5, -106.5, 25.0, 5865.26, 3753768.0)
        assert "ROI Area Calculation" in out
        assert "5865.26 square miles" in out
        assert "3,753,768 acres" in out
        assert "Center: (34.5, -106.5)" in out

    def test_roi_summary_renders_extent_and_project(self, monkeypatch):
        api = _load_roi_api()
        geojson = {"metadata": {"extent": {"north": 35.0, "south": 34.0, "east": -106.0, "west": -107.0}}}
        out = api.format_roi_summary(34.5, -106.5, 25.0, 5865.26, 3753768.0, geojson, "Test Project")
        assert "Region of Interest (ROI) Summary" in out
        assert "Project: Test Project" in out
        assert "North: 35.0" in out
        assert "West: -107.0" in out

    def test_roi_summary_defaults_unnamed_project(self, monkeypatch):
        api = _load_roi_api()
        out = api.format_roi_summary(34.5, -106.5, 25.0, 1.0, 2.0, {"metadata": {}}, None)
        assert "Project: Unnamed" in out
        # Missing extent falls back to N/A rather than crashing.
        assert "North: N/A" in out
